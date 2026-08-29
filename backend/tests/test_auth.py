from terraforge.auth import AuthStore, RegisterRequest
from terraforge.settings import Settings


async def test_auth_store_persists_users_and_sessions_without_plaintext_secrets(tmp_path):
    settings = Settings(_env_file=None, terraforge_data_dir=tmp_path)
    first = AuthStore(settings)
    await first.initialize()
    account = await first.register(
        RegisterRequest(
            name="Persistent Builder", email="persist@example.com", password="strong-pass"
        )
    )
    token, _ = await first.create_session(account)

    contents = (tmp_path / "thermasite-auth.json").read_text(encoding="utf-8")
    assert "strong-pass" not in contents
    assert token not in contents

    restored = AuthStore(settings)
    await restored.initialize()
    authenticated = await restored.authenticate(token)
    assert authenticated is not None
    assert authenticated.email == "persist@example.com"


async def test_demo_identity_is_seeded_once_and_sessions_are_revocable(tmp_path):
    settings = Settings(_env_file=None, terraforge_data_dir=tmp_path)
    store = AuthStore(settings)
    await store.initialize()
    demo = await store.demo_user()
    token, _ = await store.create_session(demo)
    assert (await store.authenticate(token)).is_demo is True
    await store.revoke(token)
    assert await store.authenticate(token) is None
