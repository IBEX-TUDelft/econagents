from jinja2 import Template
import pytest
from examples.ibex_tudelft.voting.state import HLGameState
from econagents.core.events import Message


class TestVotingState:
    @pytest.fixture
    def game_state(self):
        """Create a fresh game state for each test"""
        return HLGameState(game_id=1)

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
                    {"number": 5, "compensationRequests": [None, 425000]},
                ]
            },
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
        rendered_lines = [line.strip() for line in rendered.split("\n") if line.strip()]

        # Expected output
        expected_lines = [
            "Compensation requests (ordered from lowest to highest):",
            "- Owner 4: 150000",
            "- Owner 3: 287000",
            "- Owner 1: 370000",
            "- Owner 5: 425000",
        ]

        # Compare rendered output with expected
        assert rendered_lines == expected_lines

    def test_compensation_offers_handling(self, game_state):
        # Test case 1: Normal compensation offer
        event = Message(
            message_type="event", event_type="compensation-offer-made", data={"compensationOffers": [None, 300000]}
        )
        game_state.update(event)
        assert game_state.public_information.compensationOffers == [None, 300000]

        # Test case 2: Update existing offer
        event = Message(
            message_type="event", event_type="compensation-offer-made", data={"compensationOffers": [None, 400000]}
        )
        game_state.update(event)
        assert game_state.public_information.compensationOffers == [None, 400000]

    def test_compensation_offers_jinja_rendering(self, game_state):
        # Test compensation offer rendering
        offer_event = Message(
            message_type="event", event_type="compensation-offer-made", data={"compensationOffers": [None, 300000]}
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
        rendered_lines = [line.strip() for line in rendered.split("\n") if line.strip()]

        # Verify offer is displayed correctly
        assert rendered_lines == ["- compensation offer made: 300000"]

        # Test empty case
        empty_event = Message(
            message_type="event", event_type="compensation-offer-made", data={"compensationOffers": [None, None]}
        )
        game_state.update(empty_event)

        # Render template with empty data
        rendered_empty = template.render(public_information=game_state.public_information)
        rendered_empty_lines = [line.strip() for line in rendered_empty.split("\n") if line.strip()]

        # Verify empty case
        assert rendered_empty_lines == ["- no compensation offer made yet"]
