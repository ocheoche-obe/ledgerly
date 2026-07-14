"""WebConstruct — private S3 bucket + CloudFront distribution for the SPA (ADR-003).

The bucket blocks all public access; CloudFront reaches it via Origin Access Control (OAC),
so assets are only served over TLS through the CDN. SPA runtime config is injected as a
`config.json` object alongside the built assets in a single BucketDeployment (so pruning
never races between two deployments), letting the SPA read Cognito/API values at load time
without baking them into the build.
"""
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import RemovalPolicy
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

from ledgerly.config import StageConfig

_FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


class WebConstruct(Construct):
    def __init__(self, scope: Construct, construct_id: str, *, stage: StageConfig):
        super().__init__(scope, construct_id)

        self.bucket = s3.Bucket(
            self,
            "SiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,  # SSE-S3 (architecture §4.4)
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN if stage.retain_data else RemovalPolicy.DESTROY,
            auto_delete_objects=not stage.retain_data,
        )

        self.distribution = cloudfront.Distribution(
            self,
            "Distribution",
            comment=f"Ledgerly {stage.name} SPA",
            default_root_object="index.html",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(self.bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            # SPA client-side routing: serve index.html for not-found paths.
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403, response_http_status=200, response_page_path="/index.html"
                ),
                cloudfront.ErrorResponse(
                    http_status=404, response_http_status=200, response_page_path="/index.html"
                ),
            ],
        )

        self.site_url = f"https://{self.distribution.distribution_domain_name}"

    def deploy_spa(
        self,
        *,
        region: str,
        user_pool_id: str,
        user_pool_client_id: str,
        cognito_domain: str,
        api_url: str,
    ) -> None:
        """Deploy the built SPA + a runtime config.json in one BucketDeployment."""
        sources: list[s3deploy.ISource] = []
        if _FRONTEND_DIST.is_dir():
            sources.append(s3deploy.Source.asset(str(_FRONTEND_DIST)))
        else:
            cdk.Annotations.of(self).add_warning(
                f"frontend/dist not found at {_FRONTEND_DIST} — deploying runtime config only. "
                "Run `npm ci && npm run build` in frontend/ before `cdk deploy`."
            )

        sources.append(
            s3deploy.Source.json_data(
                "config.json",
                {
                    "region": region,
                    "userPoolId": user_pool_id,
                    "userPoolClientId": user_pool_client_id,
                    "cognitoDomain": cognito_domain,
                    "apiUrl": api_url,
                    "redirectUri": f"{self.site_url}/",
                },
            )
        )

        s3deploy.BucketDeployment(
            self,
            "DeploySpa",
            sources=sources,
            destination_bucket=self.bucket,
            distribution=self.distribution,
            distribution_paths=["/*"],  # invalidate CDN cache on each deploy
            prune=True,
        )
