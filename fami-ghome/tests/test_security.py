from __future__ import annotations

import unittest

from fami_ghome.security import make_password_hash, token_digest, verify_password


class SecurityTest(unittest.TestCase):
    def test_scrypt_hash_round_trip(self) -> None:
        hashed = make_password_hash("secret-password")
        self.assertTrue(verify_password("secret-password", hashed))
        self.assertFalse(verify_password("wrong-password", hashed))

    def test_token_digest_is_stable(self) -> None:
        digest = token_digest("secret-key", "opaque-token")
        self.assertEqual(digest, token_digest("secret-key", "opaque-token"))
        self.assertNotEqual(digest, token_digest("secret-key", "different-token"))


if __name__ == "__main__":
    unittest.main()
