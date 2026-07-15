"""AuthConstruct — Cognito user pool, hosted-UI domain, and the SPA app client (ADR-007).

Identity is Cognito; the SPA logs in via the Hosted UI using Authorization Code + PKCE
(architecture §3.5). The app client is public (no secret) — correct for a browser SPA. A
single owner user is seeded (self-signup disabled), matching the single-user MVP (ADR-006).
"""
from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_cognito as cognito
from constructs import Construct

from ledgerly.config import OWNER_EMAIL, StageConfig


class AuthConstruct(Construct):
    def __init__(self, scope: Construct, construct_id: str, *, stage: StageConfig, site_url: str):
        super().__init__(scope, construct_id)

        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name=f"ledgerly-{stage.name}",
            self_sign_up_enabled=False,  # single user, admin-created (ADR-006)
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True),
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            # TOTP available for the owner to enable; Slice 8 may make MFA required (hardening).
            mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(sms=False, otp=True),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=RemovalPolicy.RETAIN if stage.retain_data else RemovalPolicy.DESTROY,
        )

        # Hosted UI domain: https://<prefix>.auth.<region>.amazoncognito.com
        self.domain = self.user_pool.add_domain(
            "HostedUiDomain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=f"ledgerly-{stage.name}-816020558700"
            ),
        )

        # Redirect-URI allowlist: the deployed site always; the local dev SPA only in dev, so
        # the prod pool never accepts a localhost post-login redirect target.
        callback_urls = [f"{site_url}/"]
        if stage.name == "dev":
            callback_urls.append("http://localhost:5173/")
        self.user_pool_client = self.user_pool.add_client(
            "WebClient",
            user_pool_client_name=f"ledgerly-{stage.name}-web",
            generate_secret=False,  # public SPA client → PKCE, no secret
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=callback_urls,
                logout_urls=callback_urls,
            ),
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
            prevent_user_existence_errors=True,
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30),
        )

        # Seed the single owner. Cognito emails a temporary password (reset on first login).
        cognito.CfnUserPoolUser(
            self,
            "OwnerUser",
            user_pool_id=self.user_pool.user_pool_id,
            username=OWNER_EMAIL,
            desired_delivery_mediums=["EMAIL"],
            user_attributes=[
                cognito.CfnUserPoolUser.AttributeTypeProperty(name="email", value=OWNER_EMAIL),
                cognito.CfnUserPoolUser.AttributeTypeProperty(name="email_verified", value="true"),
            ],
        )

    @property
    def hosted_ui_base_url(self) -> str:
        return self.domain.base_url()
