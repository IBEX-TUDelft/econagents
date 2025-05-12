from econagents.core.agent_role import AgentRole
from econagents.llm.openai import ChatOpenAI

# For each role, create an agent class that inherits from Agent
# The prompts used by the agent are defined by a prompt resolution logic (check documentation for more details)
# In general, the goal is to make it as easy as possible for experimenters to provide prompts for the agents without
# having to write any code. This requires the LLM to do more work.


class Developer(AgentRole):
    role = 2
    name = "Developer"
    llm = ChatOpenAI()
    # These are the phases where the agent will perform an action
    task_phases = [2, 4, 5, 6]


class Owner(AgentRole):
    role = 3
    name = "Owner"
    llm = ChatOpenAI()
    # These are the phases where the agent will perform an action
    task_phases = [2, 3, 5, 6]
