import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

import websockets
from dotenv import load_dotenv
from websockets.asyncio.server import ServerConnection, serve

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

WAITING = "waiting"
MARKET = "market"
SUMMARY = "summary"
FINISHED = "finished"

SPECS_PATH = Path(__file__).parent / "games"
LOGS_DIR = Path(__file__).resolve().parents[1] / "logs"


def configure_server_file_logging(logs_dir: Path = LOGS_DIR) -> Path:
    """Write server-side market events to a persistent local log file."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "server.log"
    if not any(
        isinstance(handler, logging.FileHandler) and handler.baseFilename == str(log_file)
        for handler in logger.handlers
    ):
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(file_handler)
    logger.setLevel(logging.INFO)
    return log_file


class ContinuousDoubleAuctionGame:
    """A small continuous double auction with induced buyer values and seller costs."""

    def __init__(
        self,
        game_id: int,
        trader_specs: list[dict[str, Any]],
        market_duration: int = 10,
        summary_duration: int = 2,
    ):
        self.game_id = game_id
        self.trader_specs = trader_specs
        self.market_duration = market_duration
        self.summary_duration = summary_duration
        self.players: dict[int, Optional[ServerConnection]] = {}
        self.player_ready: dict[int, bool] = {}
        self.state = WAITING
        self.orders: dict[str, dict[int, dict[str, Any]]] = {"buy": {}, "sell": {}}
        self.transactions: list[dict[str, Any]] = []
        self.actions_submitted: dict[int, int] = {}
        self.units_bought: dict[int, int] = {}
        self.units_sold: dict[int, int] = {}
        self.cash_balance: dict[int, float] = {}
        self.cash_flow: dict[int, float] = {}
        self.surplus: dict[int, float] = {}
        self.order_count = 0
        self._lock = asyncio.Lock()
        self._close_task: asyncio.Task | None = None
        self._summary_task: asyncio.Task | None = None

    @property
    def num_players(self) -> int:
        """Return the configured number of traders."""
        return len(self.trader_specs)

    def add_player(self, player_number: int, websocket: ServerConnection) -> None:
        """Add a trader connection to the game."""
        self.players[player_number] = websocket
        self.player_ready[player_number] = False
        self.actions_submitted[player_number] = 0
        self.units_bought[player_number] = 0
        self.units_sold[player_number] = 0
        self.cash_balance[player_number] = self.initial_cash_balance(player_number)
        self.cash_flow[player_number] = 0.0
        self.surplus[player_number] = 0.0
        logger.info(f"Added player {player_number} to game {self.game_id}")

    def all_players_joined(self) -> bool:
        """Return whether every configured trader has joined."""
        return len(self.players) == self.num_players

    def all_players_ready(self) -> bool:
        """Return whether every joined trader has sent ready."""
        return self.all_players_joined() and all(self.player_ready.values())

    def player_spec(self, player_number: int) -> dict[str, Any]:
        """Return the trader spec for a player number."""
        return self.trader_specs[player_number - 1]

    def initial_cash_balance(self, player_number: int) -> float:
        """Return the starting cash assigned to a trader."""
        spec = self.player_spec(player_number)
        if "cash_endowment" in spec:
            return float(spec["cash_endowment"])
        if spec["trader_type"] == "buyer":
            return float(sum(spec["limit_prices"]))
        return 0.0

    def player_number_for_recovery(self, recovery: str) -> int | None:
        """Resolve a recovery code to a one-based player number."""
        for index, spec in enumerate(self.trader_specs, start=1):
            if spec["recovery"] == recovery:
                return index
        return None

    def record_order(self, player_number: int, side: str, price: float) -> None:
        """Record or replace one active order for the trader."""
        spec = self.player_spec(player_number)
        expected_side = "buy" if spec["trader_type"] == "buyer" else "sell"
        if side != expected_side:
            raise ValueError(f"Player {player_number} is a {spec['trader_type']} and cannot submit {side} orders")
        if self.remaining_units(player_number) <= 0:
            raise ValueError(f"Player {player_number} has no remaining units to trade")
        if price <= 0:
            raise ValueError("Order price must be positive")
        limit_price = self.current_limit_price(player_number)
        if limit_price is None:
            raise ValueError(f"Player {player_number} has no remaining limit price")
        if expected_side == "buy":
            if price > limit_price:
                raise ValueError(f"Buyer {player_number} cannot bid above current value {limit_price:.2f}")
            if price > self.cash_balance[player_number]:
                raise ValueError(
                    f"Buyer {player_number} cannot bid above cash balance {self.cash_balance[player_number]:.2f}"
                )
        elif price < limit_price:
            raise ValueError(f"Seller {player_number} cannot ask below current cost {limit_price:.2f}")

        self.actions_submitted[player_number] += 1
        self.order_count += 1
        self.orders[side][player_number] = {
            "player_number": player_number,
            "side": side,
            "price": round(price, 2),
            "sequence": self.order_count,
        }
        logger.info(f"Player {player_number} submitted {side} order at {price:.2f}")
        self.match_orders()

    def record_hold(self, player_number: int) -> None:
        """Record that a trader chose not to quote on this tick."""
        self.actions_submitted[player_number] += 1
        if self.remaining_units(player_number) <= 0:
            self.orders["buy"].pop(player_number, None)
            self.orders["sell"].pop(player_number, None)

    def match_orders(self) -> None:
        """Match crossed bid and ask orders until the book is no longer crossed."""
        while self.orders["buy"] and self.orders["sell"]:
            bid = max(self.orders["buy"].values(), key=lambda order: (order["price"], -order["sequence"]))
            ask = min(self.orders["sell"].values(), key=lambda order: (order["price"], order["sequence"]))

            if bid["price"] < ask["price"]:
                break

            buyer = bid["player_number"]
            seller = ask["player_number"]
            if self.remaining_units(buyer) <= 0:
                self.orders["buy"].pop(buyer, None)
                continue
            if self.remaining_units(seller) <= 0:
                self.orders["sell"].pop(seller, None)
                continue
            buyer_value = self.current_limit_price(buyer)
            seller_cost = self.current_limit_price(seller)
            if buyer_value is None:
                self.orders["buy"].pop(buyer, None)
                continue
            if seller_cost is None:
                self.orders["sell"].pop(seller, None)
                continue

            price = round((bid["price"] + ask["price"]) / 2, 2)
            buyer_surplus = round(buyer_value - price, 2)
            seller_surplus = round(price - seller_cost, 2)
            self.units_bought[buyer] += 1
            self.units_sold[seller] += 1
            self.cash_balance[buyer] = round(self.cash_balance[buyer] - price, 2)
            self.cash_balance[seller] = round(self.cash_balance[seller] + price, 2)
            self.cash_flow[buyer] = round(self.cash_flow[buyer] - price, 2)
            self.cash_flow[seller] = round(self.cash_flow[seller] + price, 2)
            self.surplus[buyer] = round(self.surplus[buyer] + buyer_surplus, 2)
            self.surplus[seller] = round(self.surplus[seller] + seller_surplus, 2)
            transaction = {
                "trade": len(self.transactions) + 1,
                "price": price,
                "buyer": buyer,
                "seller": seller,
                "bid": bid["price"],
                "ask": ask["price"],
                "buyer_value": buyer_value,
                "seller_cost": seller_cost,
                "buyer_surplus": buyer_surplus,
                "seller_surplus": seller_surplus,
            }
            self.transactions.append(transaction)
            logger.info(f"Trade {transaction['trade']}: buyer {buyer} and seller {seller} at {price:.2f}")

            self.orders["buy"].pop(buyer, None)
            self.orders["sell"].pop(seller, None)
            self.remove_exhausted_orders()

    def remove_exhausted_orders(self) -> None:
        """Drop active orders from traders with no remaining marginal units."""
        for side in ("buy", "sell"):
            for player_number in list(self.orders[side]):
                if self.remaining_units(player_number) <= 0:
                    self.orders[side].pop(player_number, None)

    def remaining_units(self, player_number: int) -> int:
        """Return how many units the trader can still buy or sell."""
        spec = self.player_spec(player_number)
        traded = self.units_bought[player_number] if spec["trader_type"] == "buyer" else self.units_sold[player_number]
        return max(0, len(spec["limit_prices"]) - traded)

    def current_limit_price(self, player_number: int) -> float | None:
        """Return the current marginal value or cost for a trader."""
        spec = self.player_spec(player_number)
        traded = self.units_bought[player_number] if spec["trader_type"] == "buyer" else self.units_sold[player_number]
        if traded >= len(spec["limit_prices"]):
            return None
        return float(spec["limit_prices"][traded])

    def inventory(self, player_number: int) -> int:
        """Return current inventory from the trader's point of view."""
        spec = self.player_spec(player_number)
        if spec["trader_type"] == "buyer":
            return self.units_bought[player_number]
        return self.remaining_units(player_number)

    def best_bid(self) -> float | None:
        """Return the best active bid."""
        if not self.orders["buy"]:
            return None
        return max(order["price"] for order in self.orders["buy"].values())

    def best_ask(self) -> float | None:
        """Return the best active ask."""
        if not self.orders["sell"]:
            return None
        return min(order["price"] for order in self.orders["sell"].values())

    def last_price(self) -> float | None:
        """Return the most recent transaction price."""
        if not self.transactions:
            return None
        return self.transactions[-1]["price"]

    def market_summary(self) -> dict[str, Any]:
        """Return public final market results."""
        prices = [transaction["price"] for transaction in self.transactions]
        return {
            "total_trades": len(self.transactions),
            "average_price": round(sum(prices) / len(prices), 2) if prices else None,
            "total_buyer_surplus": round(sum(transaction["buyer_surplus"] for transaction in self.transactions), 2),
            "total_seller_surplus": round(sum(transaction["seller_surplus"] for transaction in self.transactions), 2),
            "total_surplus": round(sum(self.surplus.values()), 2),
        }

    def payload_for_player(self, player_number: int, phase: str = MARKET) -> dict[str, Any]:
        """Build a player-specific event payload."""
        spec = self.player_spec(player_number)
        return {
            "gameId": self.game_id,
            "phase": phase,
            "player_number": player_number,
            "trader_type": spec["trader_type"],
            "limit_price": self.current_limit_price(player_number),
            "remaining_units": self.remaining_units(player_number),
            "cash_balance": round(self.cash_balance[player_number], 2),
            "cash_flow": round(self.cash_flow[player_number], 2),
            "surplus": round(self.surplus[player_number], 2),
            "inventory": self.inventory(player_number),
            "actions_submitted": self.actions_submitted[player_number],
            "best_bid": self.best_bid(),
            "best_ask": self.best_ask(),
            "last_price": self.last_price(),
            "order_count": self.order_count,
            "transactions": self.transactions,
            "market_summary": self.market_summary() if phase in {SUMMARY, FINISHED} else {},
            "market_duration": self.market_duration,
            "summary_duration": self.summary_duration,
        }

    def all_units_traded(self) -> bool:
        """Return whether no buyer or seller has remaining units."""
        buyers_remaining = any(
            self.player_spec(player)["trader_type"] == "buyer" and self.remaining_units(player) > 0
            for player in self.players
        )
        sellers_remaining = any(
            self.player_spec(player)["trader_type"] == "seller" and self.remaining_units(player) > 0
            for player in self.players
        )
        return not buyers_remaining or not sellers_remaining


class ContinuousDoubleAuctionServer:
    """WebSocket server for a local continuous double auction experiment."""

    def __init__(self, host: str = "localhost", port: int = 8766):
        self.host = host
        self.port = port
        self.games: dict[int, ContinuousDoubleAuctionGame] = {}

    async def handle_websocket(self, websocket: ServerConnection) -> None:
        """Handle one trader connection."""
        game = None
        player_number = None

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    meta = data.get("meta") or {}
                    msg_type = meta.get("type", "")
                    payload = data.get("payload") or {}

                    if msg_type == "join":
                        game, player_number = await self.handle_join(websocket, payload)
                    elif msg_type == "ready":
                        if not game or player_number is None:
                            await self.send_error(websocket, "Join the game before declaring ready")
                            continue
                        game.player_ready[player_number] = True
                        logger.info(f"Player {player_number} is ready in game {game.game_id}")
                        if game.all_players_ready() and game.state == WAITING:
                            await self.start_market(game)
                    elif msg_type == "submit-order":
                        if not game or player_number is None:
                            await self.send_error(websocket, "Game not found")
                            continue
                        await self.handle_order(game, player_number, payload)
                    elif msg_type == "hold":
                        if game and player_number is not None:
                            async with game._lock:
                                game.record_hold(player_number)
                            await self.broadcast_market_update(game)
                    else:
                        await self.send_error(websocket, f"Unknown message type: {msg_type}")
                except json.JSONDecodeError:
                    await self.send_error(websocket, "Invalid JSON message")
                except Exception as exc:
                    logger.exception(f"Error handling message: {exc}")
                    await self.send_error(websocket, f"Error: {exc}")

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Connection closed for player {player_number}")
        finally:
            if game and player_number is not None and player_number in game.players:
                game.players[player_number] = None
                logger.info(f"Player {player_number} disconnected from game {game.game_id}")

    async def handle_join(
        self, websocket: ServerConnection, payload: dict[str, Any]
    ) -> tuple[ContinuousDoubleAuctionGame | None, int | None]:
        """Validate a join request and open the introduction phase."""
        game_id = payload.get("gameId")
        recovery = payload.get("recovery")
        if game_id is None or not recovery:
            await self.send_error(websocket, "Game ID and recovery code are required")
            return None, None

        game_specs_path = SPECS_PATH / f"game_{game_id}.json"
        if not game_specs_path.exists():
            await self.send_error(websocket, f"Game {game_id} does not exist")
            return None, None

        with game_specs_path.open("r") as f:
            game_specs = json.load(f)

        game = self.games.get(game_id)
        if game is None:
            game = ContinuousDoubleAuctionGame(
                game_id=game_id,
                trader_specs=game_specs["traders"],
                market_duration=game_specs.get("market_duration", 10),
                summary_duration=game_specs.get("summary_duration", 2),
            )
            self.games[game_id] = game

        player_number = game.player_number_for_recovery(recovery)
        if player_number is None:
            await self.send_error(websocket, f"Invalid recovery code: {recovery}")
            return None, None
        if player_number in game.players and game.players[player_number] is not None:
            await self.send_error(websocket, f"Player {player_number} already joined")
            return None, None

        game.add_player(player_number, websocket)
        await self.send_phase_transition(
            websocket,
            "introduction",
            {
                "gameId": game.game_id,
                "player_number": player_number,
                "players": [
                    {"recovery": spec["recovery"], "playerNumber": idx + 1}
                    for idx, spec in enumerate(game.trader_specs)
                ],
            },
        )
        return game, player_number

    async def start_market(self, game: ContinuousDoubleAuctionGame) -> None:
        """Open the continuous market phase."""
        game.state = MARKET
        logger.info(f"Game {game.game_id} market opened")
        for player_number, websocket in game.players.items():
            if websocket:
                await self.send_phase_transition(websocket, MARKET, game.payload_for_player(player_number))

        game._close_task = asyncio.create_task(self.close_market_after_duration(game))

    async def handle_order(
        self, game: ContinuousDoubleAuctionGame, player_number: int, payload: dict[str, Any]
    ) -> None:
        """Process one submitted order and broadcast the resulting market state."""
        if game.state != MARKET:
            websocket = game.players.get(player_number)
            if websocket:
                await self.send_error(websocket, "Market is not open")
            return

        try:
            side = payload.get("side")
            price = payload.get("price")
            if side not in {"buy", "sell"}:
                raise ValueError("side must be 'buy' or 'sell'")
            if price is None:
                raise ValueError("price is required")
            async with game._lock:
                game.record_order(player_number, side, float(price))
        except ValueError as exc:
            websocket = game.players.get(player_number)
            if websocket:
                await self.send_error(websocket, str(exc))
            return

        await self.broadcast_market_update(game)
        if game.all_units_traded():
            await self.end_market(game)

    async def close_market_after_duration(self, game: ContinuousDoubleAuctionGame) -> None:
        """Close the market after the configured duration."""
        try:
            await asyncio.sleep(game.market_duration)
            await self.end_market(game)
        except asyncio.CancelledError:
            logger.debug(f"Market close task cancelled for game {game.game_id}")

    async def end_market(self, game: ContinuousDoubleAuctionGame) -> None:
        """End the market and notify agents of final results."""
        if game.state in {SUMMARY, FINISHED}:
            return
        game.state = SUMMARY
        if game._close_task is not None and game._close_task is not asyncio.current_task():
            game._close_task.cancel()
        game._close_task = None

        logger.info(f"Game {game.game_id} market ended with {len(game.transactions)} trades")
        for player_number, websocket in game.players.items():
            if websocket:
                await self.send_phase_transition(
                    websocket, SUMMARY, game.payload_for_player(player_number, phase=SUMMARY)
                )

        game._summary_task = asyncio.create_task(self.finish_game_after_summary(game))

    async def finish_game_after_summary(self, game: ContinuousDoubleAuctionGame) -> None:
        """Give clients a short final-results phase before ending the game."""
        try:
            await asyncio.sleep(game.summary_duration)
            await self.finish_game(game)
        except asyncio.CancelledError:
            logger.debug(f"Summary close task cancelled for game {game.game_id}")

    async def finish_game(self, game: ContinuousDoubleAuctionGame) -> None:
        """Finish the game after final results have been sent."""
        if game.state == FINISHED:
            return
        game.state = FINISHED
        if game._summary_task is not None and game._summary_task is not asyncio.current_task():
            game._summary_task.cancel()
        game._summary_task = None

        logger.info(f"Game {game.game_id} ended with {len(game.transactions)} trades")
        for player_number, websocket in game.players.items():
            if websocket:
                await self.send_event(websocket, "game-over", game.payload_for_player(player_number, phase=FINISHED))

    async def broadcast_market_update(self, game: ContinuousDoubleAuctionGame) -> None:
        """Broadcast a player-specific market update to every connected trader."""
        if game.state != MARKET:
            return
        for player_number, websocket in game.players.items():
            if websocket:
                await self.send_event(websocket, "market-update", game.payload_for_player(player_number))

    async def send_event(self, websocket: ServerConnection, event_type: str, payload: dict[str, Any]) -> None:
        """Send a standard IBEX-style event envelope."""
        await websocket.send(json.dumps({"meta": {"type": event_type}, "payload": payload}))

    async def send_error(self, websocket: ServerConnection, error_message: str) -> None:
        """Send an error event to a client."""
        await self.send_event(websocket, "error", {"message": error_message})

    async def send_phase_transition(
        self, websocket: ServerConnection, phase: str, extra: Optional[dict[str, Any]] = None
    ) -> None:
        """Send a phase-transition event."""
        await self.send_event(websocket, "phase-transition", {"phase": phase, **(extra or {})})

    async def start_server(self) -> None:
        """Start the WebSocket server."""
        async with serve(self.handle_websocket, self.host, self.port):
            logger.info(f"Continuous Double Auction server started on {self.host}:{self.port}")
            await asyncio.Future()

    @classmethod
    async def run(cls, host: str = "localhost", port: int = 8766) -> None:
        """Run the WebSocket server."""
        server = cls(host, port)
        await server.start_server()


if __name__ == "__main__":
    log_path = configure_server_file_logging()
    logger.info(f"Writing server log to {log_path}")
    asyncio.run(ContinuousDoubleAuctionServer.run())
