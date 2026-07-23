from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from app.config import AppSettings
from app.services.transactional_email import (
    PasswordResetDelivery,
    TencentSesTransactionalEmailProvider,
    TransactionalEmailError,
    VerificationDelivery,
    build_transactional_email_provider,
)


def _settings(tmp_path: Path, **overrides: object) -> AppSettings:
    values: dict[str, object] = {
        "project_dir": tmp_path,
        "data_dir": tmp_path / "data",
        "upload_dir": tmp_path / "data" / "uploads",
        "database_url": "sqlite://",
        "transactional_email_provider": "tencent_ses",
        "transactional_email_from": "GreatSell AI <noreply@mail.example.test>",
        "public_app_url": "https://hr.example.test",
        "tencent_secret_id": "ses-secret-id-fixture",
        "tencent_secret_key": "ses-secret-key-fixture",
        "tencent_ses_region": "ap-guangzhou",
        "tencent_ses_verification_template_id": 101,
        "tencent_ses_password_reset_template_id": 202,
    }
    values.update(overrides)
    return AppSettings(**values)  # type: ignore[arg-type]


class _SesClientCapture:
    instances: list["_SesClientCapture"] = []

    def __init__(self, credential: object, region: str) -> None:
        self.credential = credential
        self.region = region
        self.requests: list[object] = []
        self.__class__.instances.append(self)

    def SendEmail(self, request: object) -> object:
        self.requests.append(request)
        return object()


def _verification_delivery() -> VerificationDelivery:
    return VerificationDelivery(
        recipient="candidate@example.test",
        verification_url="https://hr.example.test/verify-email?token=fixture-token",
        expires_minutes=60,
    )


def _password_reset_delivery() -> PasswordResetDelivery:
    return PasswordResetDelivery(
        recipient="candidate@example.test",
        reset_url="https://hr.example.test/reset-password?token=fixture-token",
        expires_minutes=30,
    )


def test_tencent_ses_verification_uses_the_approved_template_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tencentcloud.ses.v20201002 import ses_client

    _SesClientCapture.instances.clear()
    monkeypatch.setattr(ses_client, "SesClient", _SesClientCapture)
    settings = _settings(tmp_path)
    settings.validate_runtime()

    provider = build_transactional_email_provider(settings)
    assert isinstance(provider, TencentSesTransactionalEmailProvider)
    provider.send_email_verification(_verification_delivery())

    captured = _SesClientCapture.instances[-1]
    assert captured.region == "ap-guangzhou"
    request = captured.requests[-1]
    assert request.FromEmailAddress == "GreatSell AI <noreply@mail.example.test>"
    assert request.Subject == "验证你的 GreatSell AI 工作邮箱"
    assert request.Destination == ["candidate@example.test"]
    assert request.TriggerType == 1
    assert request.Template.TemplateID == 101
    assert json.loads(request.Template.TemplateData) == {
        "verify_url": "https://hr.example.test/verify-email?token=fixture-token",
        "expires_minutes": "60",
    }


def test_tencent_ses_password_reset_uses_a_different_approved_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tencentcloud.ses.v20201002 import ses_client

    _SesClientCapture.instances.clear()
    monkeypatch.setattr(ses_client, "SesClient", _SesClientCapture)
    provider = build_transactional_email_provider(_settings(tmp_path))

    provider.send_password_reset(_password_reset_delivery())

    captured = _SesClientCapture.instances[-1]
    request = captured.requests[-1]
    assert request.FromEmailAddress == "GreatSell AI <noreply@mail.example.test>"
    assert request.Subject == "重置你的 GreatSell AI 登录密码"
    assert request.Destination == ["candidate@example.test"]
    assert request.TriggerType == 1
    assert request.Template.TemplateID == 202
    assert json.loads(request.Template.TemplateData) == {
        "reset_url": "https://hr.example.test/reset-password?token=fixture-token",
        "expires_minutes": "30",
    }


def test_tencent_ses_requires_a_dedicated_password_reset_template(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="TENCENT_SES_PASSWORD_RESET_TEMPLATE_ID"):
        _settings(tmp_path, tencent_ses_password_reset_template_id=None).validate_runtime()


def test_tencent_ses_rejects_an_unsupported_region_before_delivery(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="TENCENT_SES_REGION"):
        _settings(tmp_path, tencent_ses_region="ap-beijing").validate_runtime()


def test_tencent_ses_hides_provider_details_on_delivery_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
        TencentCloudSDKException,
    )
    from tencentcloud.ses.v20201002 import ses_client

    class _FailingSesClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def SendEmail(self, _: object) -> object:
            raise TencentCloudSDKException(
                "AuthFailure.SecretIdNotFound",
                "provider-detail-that-must-not-reach-logs",
            )

    monkeypatch.setattr(ses_client, "SesClient", _FailingSesClient)
    caplog.set_level(logging.WARNING)
    provider = build_transactional_email_provider(_settings(tmp_path))

    with pytest.raises(TransactionalEmailError, match="email_delivery_provider_failed"):
        provider.send_email_verification(_verification_delivery())

    assert "ses-secret-id-fixture" not in caplog.text
    assert "ses-secret-key-fixture" not in caplog.text
    assert "candidate@example.test" not in caplog.text
    assert "fixture-token" not in caplog.text
    assert "provider-detail-that-must-not-reach-logs" not in caplog.text
