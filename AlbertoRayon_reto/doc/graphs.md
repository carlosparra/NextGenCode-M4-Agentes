# Grafos de los agentes

Generado con `python scripts/export_graphs.py`. No editar a mano.

## Supervisor con especialistas

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	supervisor(supervisor)
	directory_agent(directory_agent)
	vacation_agent(vacation_agent)
	summary_agent(summary_agent)
	__end__([<p>__end__</p>]):::last
	__start__ --> supervisor;
	supervisor -.-> directory_agent;
	supervisor -.-> summary_agent;
	supervisor -.-> vacation_agent;
	directory_agent --> __end__;
	summary_agent --> __end__;
	vacation_agent --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

## Agente ReAct (directorio y vacaciones)

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	model(model)
	tools(tools)
	cap(cap)
	__end__([<p>__end__</p>]):::last
	__start__ --> model;
	model -. &nbsp;end&nbsp; .-> __end__;
	model -.-> cap;
	model -.-> tools;
	tools -. &nbsp;end&nbsp; .-> __end__;
	tools -.-> model;
	cap --> __end__;
	model -.-> model;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

## Agente de reflexión (resúmenes)

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	gather_facts(gather_facts)
	draft(draft)
	critique(critique)
	revise(revise)
	finalize(finalize)
	__end__([<p>__end__</p>]):::last
	__start__ --> gather_facts;
	critique -.-> finalize;
	critique -.-> revise;
	draft --> critique;
	gather_facts --> draft;
	revise --> critique;
	finalize --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```
