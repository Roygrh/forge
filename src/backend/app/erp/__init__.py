"""MeridianERP — the simulated client system of record (an external system, not Forge).

See :mod:`app.erp.store` for why this lives outside Forge's own database, and
:mod:`app.erp.facts` for the line between what the ERP observes (facts) and what the
governed rule set decides (:mod:`app.rules`).
"""

from app.erp.facts import FactValue, build_fact_sheet
from app.erp.records import GoodsReceipt, Invoice, PostedAction, PurchaseOrder, Vendor
from app.erp.seed_data import DEMO_INVOICE_ID, ERP_TODAY
from app.erp.store import ErpError, ErpStore, get_erp, reset_erp

__all__ = [
    "DEMO_INVOICE_ID",
    "ERP_TODAY",
    "ErpError",
    "ErpStore",
    "FactValue",
    "GoodsReceipt",
    "Invoice",
    "PostedAction",
    "PurchaseOrder",
    "Vendor",
    "build_fact_sheet",
    "get_erp",
    "reset_erp",
]
