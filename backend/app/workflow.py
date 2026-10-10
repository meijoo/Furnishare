"""LangGraph planning workflow: retrieve/filter/rank/select/layout/validate -> publish -> explain.

Approvals are not graph state: the application tables are the source of truth while waiting on roommates.
"""
from typing import TypedDict

from . import core, planner
from .core import Conflict
from .money import dollars

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover
    StateGraph = None


class PlanState(TypedDict, total=False):
    household_id: str
    categories: list[str]
    budget_cents: int
    style_text: str
    picks: list[dict]
    skip_categories: list[str]
    products: list[dict]
    scene: list[dict]
    rank_mode: str
    proposal_version: int
    error: str
    message: str


def _plan(s: PlanState) -> PlanState:
    result = planner.select_bundle(s['household_id'], s['categories'], s['budget_cents'], s['style_text'],
                                  picks=s.get('picks'), skip_categories=s.get('skip_categories'))
    if not result['ok']:
        return {'error': ' '.join(result['notes'])}
    return {'products': result['products'], 'rank_mode': result['rank_mode']}


def _publish(s: PlanState) -> PlanState:
    picks = ', '.join(f"{p['title']} ({dollars(p['price_cents'])})" for p in s['products'])
    explanation = f"Picked the best visual matches (ranker: {s['rank_mode']}) that fit the room and budget: {picks}."
    try:
        p = planner.propose(s['household_id'], s['products'], explanation, activity='New furnishing plan proposed')
    except (ValueError, Conflict) as e:
        return {'error': str(e)}
    return {'proposal_version': p['version']}


def _explain(s: PlanState) -> PlanState:
    if s.get('error'):
        return {'message': f"I couldn't build a plan: {s['error']}"}
    p = core.proposal(s['household_id'], s['proposal_version'])
    unknown = f" Not included: {', '.join(p['unknown_costs'])}." if p['unknown_costs'] else ''
    return {'message': f"Proposal v{p['version']} is on the iPad: {dollars(p['known_total_cents'])} known cost.{unknown} "
                       'Each roommate got their exact share privately for approval.'}


def _route(s: PlanState) -> str:
    return 'explain' if s.get('error') else 'publish'


_graph = None


def graph():
    global _graph
    if _graph is None and StateGraph is not None:
        g = StateGraph(PlanState)
        g.add_node('plan', _plan)
        g.add_node('publish', _publish)
        g.add_node('explain', _explain)
        g.set_entry_point('plan')
        g.add_conditional_edges('plan', _route, {'publish': 'publish', 'explain': 'explain'})
        g.add_edge('publish', 'explain')
        g.add_edge('explain', END)
        _graph = g.compile()
    return _graph


def run(hid: str, categories: list[str], budget_cents: int, style_text: str,
        picks: list[dict] | None = None, skip_categories: list[str] | None = None) -> PlanState:
    state: PlanState = {'household_id': hid, 'categories': categories, 'budget_cents': budget_cents,
                        'style_text': style_text, 'picks': picks or [], 'skip_categories': skip_categories or []}
    g = graph()
    if g is not None:
        return g.invoke(state)
    state.update(_plan(state))
    if not state.get('error'):
        state.update(_publish(state))
    state.update(_explain(state))
    return state
