from econagents.core.agent_role import AgentRole
from econagents.llm.openai import ChatOpenAI


class Speculator(AgentRole):
    role = 1
    name = "Speculator"
    llm = ChatOpenAI(model_name="gpt-4.1-mini")
    # These are the phases where the agent will perform an action
    task_phases = [3, 6, 8]


class Developer(AgentRole):
    role = 2
    name = "Developer"
    llm = ChatOpenAI(model_name="gpt-4.1-mini")
    # These are the phases where the agent will perform an action
    task_phases = [2, 6, 7]


class Owner(AgentRole):
    role = 3
    name = "Owner"
    llm = ChatOpenAI(model_name="gpt-4.1-mini")
    # These are the phases where the agent will perform an action
    task_phases = [2, 6, 7]
