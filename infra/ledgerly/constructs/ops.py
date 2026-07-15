"""OpsConstruct — cost guardrails (architecture §4.7, NFR-1.2).

Ships the billing alarm before anything earns traffic: an AWS Budget on the account with
two email notifications — actual > $5 and forecast > $8 — against the $10/month ceiling
(NFR-1.1). Because the Ledgerly account is dedicated (ADR-010), the account cost *is*
Ledgerly's spend, and Bedrock/LLM cost rides the same bill (ADR-008), so this one alarm
covers the whole app.
"""
from aws_cdk import aws_budgets as budgets
from constructs import Construct

from ledgerly.config import (
    BUDGET_ACTUAL_USD,
    BUDGET_FORECAST_USD,
    OWNER_EMAIL,
    StageConfig,
)

_CEILING_USD = 10  # NFR-1.1 hard ceiling; notifications fire well before it.


class OpsConstruct(Construct):
    def __init__(self, scope: Construct, construct_id: str, *, stage: StageConfig):
        super().__init__(scope, construct_id)

        def _notify(threshold: int, ntype: str) -> budgets.CfnBudget.NotificationWithSubscribersProperty:
            return budgets.CfnBudget.NotificationWithSubscribersProperty(
                notification=budgets.CfnBudget.NotificationProperty(
                    comparison_operator="GREATER_THAN",
                    threshold=threshold,
                    notification_type=ntype,  # ACTUAL | FORECASTED
                    threshold_type="ABSOLUTE_VALUE",
                ),
                subscribers=[
                    budgets.CfnBudget.SubscriberProperty(
                        subscription_type="EMAIL", address=OWNER_EMAIL
                    )
                ],
            )

        budgets.CfnBudget(
            self,
            "MonthlyCostBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name=f"ledgerly-{stage.name}-monthly",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=_CEILING_USD, unit="USD"),
            ),
            notifications_with_subscribers=[
                _notify(BUDGET_ACTUAL_USD, "ACTUAL"),
                _notify(BUDGET_FORECAST_USD, "FORECASTED"),
            ],
        )
