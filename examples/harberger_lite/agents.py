from econagents.core.agent import Agent

# For each role, create an agent class that inherits from Agent
# The prompts used by the agent are defined by a prompt resolution logic (check documentation for more details)


class Speculator(Agent):
    role = 1
    name = "Speculator"
    # These are the phases where the agent will perform an action
    task_phases = [3, 6, 8]


class Developer(Agent):
    role = 2
    name = "Developer"
    # These are the phases where the agent will perform an action
    task_phases = [2, 6, 7]


class Owner(Agent):
    role = 3
    name = "Owner"
    # These are the phases where the agent will perform an action
    task_phases = [2, 6, 7]
