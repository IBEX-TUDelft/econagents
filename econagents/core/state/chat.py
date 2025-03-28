from typing import Optional

from pydantic import BaseModel, Field, computed_field


##########################################
# structure of json with message received AI!
#{
#    "type": "message-received",
#    "data": {
#        "sender": 1,
#        "to": [
#            2,
#            3
#        ],
#        "number": 0,
#        "text": "I don't know",
#        "time": 1733497007316
#    }
#}
#

# AI class msg should be able to cover all information in a received chat
class msg(BaseModel):
    sender: int
    to: list[int]
    number: Optional[int]
    text: str
    time: int

# AI class ChatState should contain all messages
#  messages should be grouped by the content of the "to" field
#  messages in each group should be ordered by time from oldest to newest
# 
class ChatState(BaseModel):
    """
    Represents the current state of the chat:
    - History of messages
    """

    messages: dict[int, msg] = Field(default_factory=dict)
    
    def _on_add_msg(self, msg_data: dict):
        """
        The server is telling us a new msg has been received.
        We'll store it in self.messages .
        """
        msg_id = msg_data["number"]
        new_msg = msg(
            sender=msg_data["sender"],
            text=msg_data["text"],
            )
        self.messages[msg_id] = new_msg


    def process_event(self, event_type: str, data: dict):
        """
        Update the ChatState based on the eventType and
        event data from the server.
        """
        if event_type == "message-received":
            self._on_add_msg(data["data"])
            self.messages.append(new_msg)
        
        