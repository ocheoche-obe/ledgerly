"""
Ledgerly v1 — System Architecture Diagram Renderer
==================================================

Renders the Ledgerly v1 system architecture (docs/ledgerly-architecture.md §1) as
PNG and PDF using the `diagrams` (mingrammer) library — diagrams-as-code, so the
picture is version-controlled alongside the architecture it describes.

Regenerate after any architecture change:

    pip install diagrams          # (or: python3 -m venv .venv && .venv/bin/pip install diagrams)
    brew install graphviz         # provides the `dot` renderer (apt install graphviz on Linux)
    python render_architecture.py

Output: docs/ledgerly-architecture-diagram.png / .pdf

Conventions (per AWS architecture-diagram best practices):
- Left-to-right flow: the request enters with the user on the left and descends
  through frontend, auth, API, compute, data; the async ingest pipeline reads
  left-to-right along the bottom.
- Sibling layer clusters (not deeply nested) so graphviz lays out a clean grid.
- Orthogonal edge routing (straight, right-angled lines; minimal crossings).
- Solid arrows = data/request flow; dotted = control-plane / failure paths.
"""

from pathlib import Path

from diagrams import Diagram, Cluster, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.cost import Budgets
from diagrams.aws.database import Dynamodb
from diagrams.aws.integration import SQS
from diagrams.aws.management import Cloudwatch
from diagrams.aws.ml import Bedrock
from diagrams.aws.network import CloudFront, APIGateway
from diagrams.aws.security import Cognito
from diagrams.aws.storage import S3
from diagrams.onprem.client import User


# === Global graph styling =====================================================

graph_attr = {
    "fontsize": "18",
    "labelloc": "t",
    "pad": "0.5",
    "nodesep": "0.9",
    "ranksep": "1.3",
    "splines": "ortho",   # straight right-angle edges, AWS-diagram style
    "newrank": "true",    # global ranking across clusters — cleaner grid
    "bgcolor": "white",
}

node_attr = {"fontsize": "11"}
edge_attr = {"fontsize": "10"}

AWS_CLOUD_ATTR = {
    "bgcolor": "#F2F8FE",
    "pencolor": "#147EBA",
    "fontcolor": "#147EBA",
    "style": "dashed,rounded",
    "penwidth": "2",
    "fontsize": "14",
    "labeljust": "l",
    "margin": "22",
}

LAYER_ATTR = {
    "bgcolor": "#FFFFFF",
    "pencolor": "#888888",
    "fontcolor": "#444444",
    "style": "rounded",
    "penwidth": "1",
    "fontsize": "11",
    "labeljust": "l",
    "margin": "14",
}

OUT = str(Path(__file__).resolve().parent / "ledgerly-architecture-diagram")


# === Diagram ==================================================================

with Diagram(
    "Ledgerly v1 — System Architecture (AWS, serverless)",
    show=False,
    direction="LR",
    filename=OUT,
    outformat=["png", "pdf"],
    graph_attr=graph_attr,
    node_attr=node_attr,
    edge_attr=edge_attr,
):
    owner = User("Owner\n(browser)")

    with Cluster("AWS Cloud — us-east-1 (per stage: dev / prod)", graph_attr=AWS_CLOUD_ATTR):

        # Declaration order shapes the vertical band order (top → bottom):
        # interactive request path first, async ingest pipeline second, ops last.

        with Cluster("Frontend", graph_attr=LAYER_ATTR):
            cf = CloudFront("CloudFront\n(TLS + CDN)")
            s3_web = S3("S3: SPA assets\n(React + Vite, private)")

        with Cluster("Authentication", graph_attr=LAYER_ATTR):
            cognito = Cognito("Cognito User Pool\n(PKCE, no self-signup)")

        with Cluster("API Layer", graph_attr=LAYER_ATTR):
            apigw = APIGateway("API Gateway HTTP API\n+ JWT authorizer")

        with Cluster("Application Compute (Python 3.13)", graph_attr=LAYER_ATTR):
            api_l = Lambda("API Lambdas\nsettings · categories · budgets\ntransactions · dashboard · imports")

        with Cluster("Ingest (pluggable source: CSV now, Plaid later)", graph_attr=LAYER_ATTR):
            s3_up = S3("S3: CSV uploads\n(30-day expiry)")
            import_l = Lambda("import_handler\nparse · dedupe · summary")

        with Cluster("Async Categorization", graph_attr=LAYER_ATTR):
            queue = SQS("categorization\nqueue")
            dlq = SQS("DLQ\n(alarmed)")
            cat_l = Lambda("categorizer\nmerchant rules → LLM")

        with Cluster("AI", graph_attr=LAYER_ATTR):
            bedrock = Bedrock("Amazon Bedrock\nClaude Opus 4.8\n(IAM auth — no API key)")

        with Cluster("Data", graph_attr=LAYER_ATTR):
            ddb = Dynamodb("DynamoDB single table\n+ GSI1 (category) · GSI2 (review)\nPITR on")

        with Cluster("Observability & Cost Guards", graph_attr=LAYER_ATTR):
            cw = Cloudwatch("CloudWatch\nlogs · metrics · alarms")
            budget = Budgets("AWS Budgets\nalert $5 actual / $8 forecast")

    # --- Interactive request path (top band, left to right) -------------------
    # splines=ortho misplaces regular edge labels — use xlabel (external labels).
    owner >> cf >> s3_web
    owner >> Edge(**{"xlabel": "JWT"}) >> apigw
    owner >> Edge(style="dotted", **{"xlabel": "login"}) >> cognito
    apigw >> Edge(style="dotted", **{"xlabel": "verify"}) >> cognito
    apigw >> api_l >> ddb

    # --- Ingest + categorization pipeline (lower band, left to right) ---------
    owner >> Edge(**{"xlabel": "presigned PUT"}) >> s3_up
    s3_up >> Edge(**{"xlabel": "event"}) >> import_l
    import_l >> ddb
    import_l >> queue >> cat_l
    queue >> Edge(style="dotted", **{"xlabel": "retry ×3"}) >> dlq
    cat_l >> bedrock
    cat_l >> ddb

    # --- Invisible layout hints ------------------------------------------------
    # Keep the interactive band above the ingest band, and pin ops to the right.
    s3_web - Edge(style="invis") - s3_up
    api_l - Edge(style="invis") - queue
    ddb - Edge(style="invis") - cw
    cw - Edge(style="invis") - budget

print("Rendered: ledgerly-architecture-diagram.png + ledgerly-architecture-diagram.pdf")
