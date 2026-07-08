## BACKGROUND

Workspaces is a term representing the UX portion of athena. It seeks to make the experience of interacting with the massive agent committees - and thus athena itself - more human-like. 

It will use well-known UI components and practices but allows unprecedented access and insights to what the agents are doing as they perform their enagement.

At all times, think of agents in terms of human relationships. For example, a human with a problem just wants to summon one or more specialists to solve their problem - agents are these specialists. 

## TERMS

operator - the user of athena - a human who wants to perform a red team enagement, full cycle. Probably a leadership role of some company, bounty hunter, or someone with money - likely not fully familiar with the red teaming process, but may be.

chief orchestrator - all inputs from the operator go through the chief ochestrator, who decides the flow of the engagement

committee - a swarm of agents managed by a lead team orchestrator spawned to achieve a specific strategic goal, per the operator's statements. 

recon - team responsible for gathering best-effort intelligence on the target specified by the operator, using a variety of open and closed sources. Outputs go to the planning committee.

planning - produce a plan for the retrieval team to follow while in the field. 

retrieval - best approximation to a real hacker in the field - this is the team that executes the commdands to reach the crown jewels

reporting - taking the outputs of the retrieval committee and making a formal report of the findings - like MITRE.

artifacts - the outputs of an action of an agent. ex: recon agent performs http_get tool and discovers an exposed apache endpoint. Check the code for how these are catalogued on disk.

## PROBLEMS

- currently the entire engagement is a black-box of agent swarming activities
- operator cannot see what's going on beyond logs, nor can they supply input beyond instructions.txt

## GOALS

- allow the operator to kick off an engagement via a UI instead of instructions.txt
- allow the operator to visually see the agents working and when important information from the agents is materially available
- allow the operator to redirect or provide emphasis on certain activities to the agents 
- allow the operator to draw relationships that the agents cannot see - through the use of visuals in a UI

## UI PAGES

1. Engagement Request page - think of it like an operator writing an email and submitting attachments to the chief orchestrator
    Main Children (excluding obvious labels and styles)
    - text area for the intructions for the engagement
    - submit button

2. Dashboard page - a complex page with many visuals that allow the operator to track and interact-with the committees. Consists of many UI COMPONENTS.
    Main Children
    - committee graph
    - artifact table

## UI COMPONENTS

1. Committee Graph - a visually dynamic and interactable graph that shows the operator what the committees are doing. 

(1) -> ((2) -> (3)
           -> (4)
           -> (5))

    (1) = chief orchestrator
    (2) = recon leader
    (3,4,5) = recon specialists

The top level view of this graph will be 5 nodes: chief orchestrator, recon, planning, retrieval, reporting.

User can click on these notes and a menu will appear 
> Chief Orchestrator
    >> Chat - opens Operator Chat with the Chief Ochestrator
> Committees
    >> clicking on it will zoom into the committee and see its own local graph of agents, with the leader being the 2x the size of the others
    >> clicking on the leader will open an Operator Chat
    >> clicking on a specialist will have the following options
        >> Terminate (kills the agent process)
        >> Show Artifacts (shows what artifacts this agent produced)
        >> Metadata (lists age of agent and ID)

In practice, upon kick off of the enagement, the Chief Orchestrator will read the (no doubt) ambiguous request and ask for more information from the operator. Initially the chief orchestrator will ask a series of questions that the operator will be using in Operator Chat.

Overall visual of the graph should be non-ridig and fluid, ideally with animations when agents are spawned and flashes of color change when they identify something - they should also turn a slight shade darker of their color when they are spun down.

Ideally agents that happen upon critical or important info are animatedly moved towards the top of the committee cloud and perhaps closer to the team lead.

Each committee and the chief orchestrator will produce outputs that could be considered worthy of the operator's attention - these will appear and disappear as dialog boxes (think like a comic strip dialog cloud). 

If a committee needs operator feedback - a "Reply" link will show in the cloud - this type of cloud will not disappear unless clicked by the user. The chief orchestrator will be a significant source of these types - if at all.

If the committee - for example recon or retrieval finds something critical to the engagement success, the node should turn red. If it finds something noteworthy the node should turn yellow. Let's use the following default colors
- Chief Orchestrator - WHITE
- Recon - Orange
- Planning - Green
- Retrieval - Red
- Reporting - Gold

2. Artifact Table - a list of raw artifacts, categorically sorted by criticality 

Clicking an artifact will show a dialog with it's metadata (date collected, who collected, criticality level, content type) and a button that says View (which just opens the file - for now)

3. Operator Chat - an interface that allows the operator to chat with a target agent committee - usually channeled through the team lead or chief orchestrator