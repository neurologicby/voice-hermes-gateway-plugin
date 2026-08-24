from __future__ import annotations

from hermes_voice_gateway.pairing import PairingService


class FakePairingStore:
    def __init__(self) -> None:
        self.approved: set[tuple[str, str]] = set()

    def generate_code(self, platform: str, user_id: str, user_name: str = "") -> str | None:
        assert platform == "voice"
        assert user_id
        assert user_name
        return "AB3X-K9M2"

    def is_approved(self, platform: str, user_id: str) -> bool:
        return (platform, user_id) in self.approved

    def revoke(self, platform: str, user_id: str) -> bool:
        item = (platform, user_id)
        if item not in self.approved:
            return False
        self.approved.remove(item)
        return True


def test_pairing_code_repr_is_redacted() -> None:
    code = PairingService(FakePairingStore()).request_code("device", "Иван")
    assert code is not None
    assert code.code == "AB3X-K9M2"
    assert "AB3X-K9M2" not in repr(code)
    assert "redacted" in repr(code)


def test_approval_and_revoke_delegate_to_voice_platform() -> None:
    store = FakePairingStore()
    store.approved.add(("voice", "device"))
    service = PairingService(store)
    assert service.is_approved("device")
    assert service.revoke("device")
    assert not service.is_approved("device")
