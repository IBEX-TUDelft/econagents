from jinja2 import Template
import pytest
from examples.ibex_tudelft.voting.state import HLGameState
from econagents.core.events import Message

class TestVotingState:
    @pytest.fixture
    def game_state(self):
        """Create a fresh game state for each test"""
        return HLGameState(game_id=1)

    def test_sorted_compensation_requests(self, game_state):
        # Test compensation requests with sorting
        requests_event = Message(
            message_type="event",
            event_type="compensation-requests-received",
            data={
                "compensationRequests": [
                    {"number": 1, "compensationRequests": [None, 370000]},
                    {"number": 2},  # missing compensationRequests
                    {"number": 3, "compensationRequests": [None, 287000]},
                    {"number": 4, "compensationRequests": [None, 150000]},
                    {"number": 5, "compensationRequests": [None, 425000]}
                ]
            }
        )
        game_state.update(requests_event)
        
        processed_requests = game_state.private_information.compensationRequestsReceived
        
        # Verify sorting
        # None values should be first
        assert len(processed_requests) == 5
        
        # Check that requests are sorted
        previous_compensation = float('-inf')
        for request in processed_requests:
            if request.compensation is not None:
                assert request.compensation >= previous_compensation
                previous_compensation = request.compensation
        
        # Verify specific ordering
        compensations = [r.compensation for r in processed_requests]
        assert compensations[0] is None  # None value should be first
        assert compensations[1:] == [150000, 287000, 370000, 425000]  # Rest should be sorted

    def test_sorted_compensation_requests_edge_cases(self, game_state):
        # Test with all None values
        none_event = Message(
            message_type="event",
            event_type="compensation-requests-received",
            data={
                "compensationRequests": [
                    {"number": 1},
                    {"number": 2},
                    {"number": 3}
                ]
            }
        )
        game_state.update(none_event)
        none_processed = game_state.private_information.compensationRequestsReceived
        assert all(r.compensation is None for r in none_processed)
        
        # Test with identical values
        identical_event = Message(
            message_type="event",
            event_type="compensation-requests-received",
            data={
                "compensationRequests": [
                    {"number": 1, "compensationRequests": [None, 300000]},
                    {"number": 2, "compensationRequests": [None, 300000]},
                    {"number": 3, "compensationRequests": [None, 300000]}
                ]
            }
        )
        game_state.update(identical_event)
        identical_processed = game_state.private_information.compensationRequestsReceived
        assert all(r.compensation == 300000 for r in identical_processed)
        
        # Test with zero values
        zero_event = Message(
            message_type="event",
            event_type="compensation-requests-received",
            data={
                "compensationRequests": [
                    {"number": 1, "compensationRequests": [None, 0]},
                    {"number": 2, "compensationRequests": [None, 100000]},
                    {"number": 3, "compensationRequests": [None, 0]}
                ]
            }
        )
        game_state.update(zero_event)
        zero_processed = game_state.private_information.compensationRequestsReceived
        assert zero_processed[0].compensation == 0
        assert zero_processed[1].compensation == 0
        assert zero_processed[2].compensation == 100000

    def test_compensation_requests_jinja_rendering(self, game_state):
        # Setup test data
        requests_event = Message(
            message_type="event",
            event_type="compensation-requests-received",
            data={
                "compensationRequests": [
                    {"number": 1, "compensationRequests": [None, 370000]},
                    {"number": 2},  # missing compensationRequests
                    {"number": 3, "compensationRequests": [None, 287000]},
                    {"number": 4, "compensationRequests": [None, 150000]},
                    {"number": 5, "compensationRequests": [None, 425000]}
                ]
            }
        )
        game_state.update(requests_event)

        # Define the template string
        template_string = """
        {% if private_information.compensationRequestsReceived %}
            Compensation requests (ordered from lowest to highest):
            {% for request in private_information.compensationRequestsReceived %}
                {% if request.compensation is not none %}
                    - Owner {{request.number}}: {{request.compensation}}
                {% endif %}
            {% endfor %}
        {% else %}
            - No compensation requests received yet
        {% endif %}
        """

        # Create and render template
        template = Template(template_string)
        rendered = template.render(private_information=game_state.private_information)

        # Clean up whitespace for comparison
        rendered_lines = [line.strip() for line in rendered.split('\n') if line.strip()]

        # Expected output
        expected_lines = [
            "Compensation requests (ordered from lowest to highest):",
            "- Owner 4: 150000",
            "- Owner 3: 287000",
            "- Owner 1: 370000",
            "- Owner 5: 425000"
        ]

        # Compare rendered output with expected
        assert rendered_lines == expected_lines

        # Test empty case
        empty_event = Message(
            message_type="event",
            event_type="compensation-requests-received",
            data={
                "compensationRequests": []
            }
        )
        game_state.update(empty_event)

        # Render template with empty data
        rendered_empty = template.render(private_information=game_state.private_information)
        rendered_empty_lines = [line.strip() for line in rendered_empty.split('\n') if line.strip()]
        
        # Verify empty case
        assert rendered_empty_lines == ["- No compensation requests received yet"]

    def test_compensation_offers_jinja_rendering(self, game_state):
        # Test compensation offer rendering
        offer_event = Message(
            message_type="event",
            event_type="compensation-offer-made",
            data={
                "compensationOffers": [None, 300000]
            }
        )
        game_state.update(offer_event)

        # Define the template string
        template_string = """
        {% if public_information.compensationOffers and public_information.compensationOffers[1] %}
            - compensation offer made: {{public_information.compensationOffers[1]}}
        {% else %}
            - no compensation offer made yet
        {% endif %}
        """

        # Create and render template
        template = Template(template_string)
        rendered = template.render(public_information=game_state.public_information)

        # Clean up whitespace for comparison
        rendered_lines = [line.strip() for line in rendered.split('\n') if line.strip()]

        # Verify offer is displayed correctly
        assert rendered_lines == ["- compensation offer made: 300000"]

        # Test empty case
        empty_event = Message(
            message_type="event",
            event_type="compensation-offer-made",
            data={
                "compensationOffers": [None, None]
            }
        )
        game_state.update(empty_event)

        # Render template with empty data
        rendered_empty = template.render(public_information=game_state.public_information)
        rendered_empty_lines = [line.strip() for line in rendered_empty.split('\n') if line.strip()]
        
        # Verify empty case
        assert rendered_empty_lines == ["- no compensation offer made yet"]

    def test_compensation_offer_event_handling(self, game_state):
        # Test case 1: Normal compensation offer
        event = Message(
            message_type="event",
            event_type="compensation-offer-made",
            data={
                "compensationOffers": [None, 300000]
            }
        )
        game_state.update(event)
        assert game_state.public_information.compensationOffers == [None, 300000]

        # Test case 2: Update existing offer
        event = Message(
            message_type="event",
            event_type="compensation-offer-made",
            data={
                "compensationOffers": [None, 400000]
            }
        )
        game_state.update(event)
        assert game_state.public_information.compensationOffers == [None, 400000]

        # Test case 3: Zero offer
        event = Message(
            message_type="event",
            event_type="compensation-offer-made",
            data={
                "compensationOffers": [None, 0]
            }
        )
        game_state.update(event)
        assert game_state.public_information.compensationOffers == [None, 0]

    def test_compensation_offer_edge_cases(self, game_state):
        # Test case 1: Missing compensationOffers in data
        event = Message(
            message_type="event",
            event_type="compensation-offer-made",
            data={}
        )
        game_state.update(event)
        assert game_state.public_information.compensationOffers == [None, 0]  # Should use default value

        # Test case 2: Invalid offer structure
        event = Message(
            message_type="event",
            event_type="compensation-offer-made",
            data={
                "compensationOffers": [100000]  # Missing the null element
            }
        )
        game_state.update(event)
        assert game_state.public_information.compensationOffers == [None, 0]  # Should use default value

        # Test case 3: Negative offer
        event = Message(
            message_type="event",
            event_type="compensation-offer-made",
            data={
                "compensationOffers": [None, -50000]
            }
        )
        game_state.update(event)
        assert game_state.public_information.compensationOffers == [None, 0]  # Should use default value

    def test_compensation_offer_integration(self, game_state):
        """Test compensation offers in context of other game events"""
        # Setup initial game state
        setup_event = Message(
            message_type="event",
            event_type="game-setup",
            data={
                "players": [
                    {"number": 1, "name": "Developer"},
                    {"number": 2, "name": "Owner1"},
                    {"number": 3, "name": "Owner2"}
                ],
                "phase": 4
            }
        )
        game_state.update(setup_event)

        # Make compensation offer
        offer_event = Message(
            message_type="event",
            event_type="compensation-offer-made",
            data={
                "compensationOffers": [None, 300000]
            }
        )
        game_state.update(offer_event)

        # Verify state
        assert game_state.meta.phase == 4
        assert len(game_state.meta.players) == 3
        assert game_state.public_information.compensationOffers == [None, 300000]

        # Test that compensation offer persists through other events
        phase_change = Message(
            message_type="event",
            event_type="phase-change",
            data={"phase": 5}
        )
        game_state.update(phase_change)
        assert game_state.public_information.compensationOffers == [None, 300000]