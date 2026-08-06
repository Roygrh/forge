"""The governed rule set — business rules as **data**, not as code.

Meridian's tacit rules (R-001 … R-092) are rows in the ``rules`` table, each carrying
its id, the statement its owner signed off, its authority level, and a machine-readable
condition tree with the action it implies. The invoice-validator agent contains none of
them: it retrieves them through the tool gateway (``query_rules``) and reasons over what
came back, citing the ids it applied (R-092).

**How a rule change reaches production without a redeploy.**

    UPDATE rules
       SET clauses = jsonb_set(clauses, '{0,when,value}', '8000')
     WHERE rule_id = 'R-020';

The next run picks it up. There is no cache to invalidate and no image to rebuild:
``app.api.deps.get_tool_gateway`` loads the rule set from the database on every request
(:mod:`app.rules.repository`), the ``query_rules`` tool evaluates whatever it loaded
(:mod:`app.rules.engine`), and the agent decides from that. ``tests/test_ap_agents.py``
proves it end to end by editing a threshold mid-suite and watching the same invoice
change outcome.

The layers:

* :mod:`app.rules.model`      — what a rule is (condition grammar, clauses, matches).
* :mod:`app.rules.engine`     — a general interpreter for that grammar. No thresholds.
* :mod:`app.rules.catalog`    — the seed encoding of the source document. Not read at
                                run time; ``scripts/seed.py`` writes it to the table.
* :mod:`app.rules.repository` — loading the rules in force out of the database.

Phase 4.3 adds the semantic half of the knowledge layer (policy PDFs, embeddings,
authority-ranked retrieval) beside this structured half; ``authority_level`` is already
on the same scale so the two can be ranked against each other.
"""

from app.rules.catalog import CATALOG, RULESET_VERSION, catalog_rule_set
from app.rules.engine import RuleEvaluationError, evaluate
from app.rules.model import Clause, Condition, Rule, RuleMatch, RuleSet
from app.rules.repository import load_rule_set, load_rule_set_sync

__all__ = [
    "CATALOG",
    "RULESET_VERSION",
    "Clause",
    "Condition",
    "Rule",
    "RuleEvaluationError",
    "RuleMatch",
    "RuleSet",
    "catalog_rule_set",
    "evaluate",
    "load_rule_set",
    "load_rule_set_sync",
]
