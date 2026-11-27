import unittest
from uuid import uuid4
from cloud.ai_secrets import SecretCipher,SecretError,Envelope

class TestSecrets(unittest.TestCase):
    def test_encryption_and_context(self):
        tenant=str(uuid4())
        secret="fictional-key"
        cipher=SecretCipher({"v1":b"a"*32},"v1")
        one=cipher.encrypt(tenant,"deepseek",secret)
        two=cipher.encrypt(tenant,"deepseek",secret)
        self.assertNotEqual(one.nonce,two.nonce)
        self.assertNotIn(secret.encode(),one.ciphertext)
        self.assertNotIn(secret,repr(one))
        self.assertEqual(cipher.decrypt(tenant,"deepseek",one),secret)
        for t,p in ((str(uuid4()),"deepseek"),(tenant,"anthropic")):
            with self.assertRaises(SecretError):
                cipher.decrypt(t,p,one)
        altered=Envelope(one.key_version,one.nonce,one.ciphertext[:-1]+bytes([one.ciphertext[-1]^1]))
        with self.assertRaises(SecretError):
            cipher.decrypt(tenant,"deepseek",altered)
    def test_rotation(self):
        tenant=str(uuid4())
        old=SecretCipher({"old":b"a"*32},"old")
        envelope=old.encrypt(tenant,"openai","fictional-key")
        new=SecretCipher({"old":b"a"*32,"new":b"b"*32},"new")
        self.assertEqual(new.decrypt(tenant,"openai",envelope),"fictional-key")
        self.assertEqual(new.encrypt(tenant,"openai","fictional-key").key_version,"new")
        with self.assertRaises(SecretError):
            SecretCipher({"new":b"b"*32},"new").decrypt(tenant,"openai",envelope)
