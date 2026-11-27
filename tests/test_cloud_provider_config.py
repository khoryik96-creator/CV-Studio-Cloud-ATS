import unittest
from cloud.ai_dispatch import ModelPolicy
from cloud.provider_config import ProviderCatalogue,ProviderConfigError

class TestProviderCatalogue(unittest.TestCase):
    def test_explicit_price_and_model_allowlist(self):
        p=ModelPolicy("deepseek","synthetic-model",100,200,4096,1024)
        catalog=ProviderCatalogue([p])
        self.assertIs(catalog.get("deepseek","synthetic-model"),p)
        with self.assertRaises(ProviderConfigError):
            catalog.get("deepseek","unknown")
        with self.assertRaises(ProviderConfigError):
            ProviderCatalogue([p,p])
        with self.assertRaises(ProviderConfigError):
            ProviderCatalogue([ModelPolicy("deepseek","unpriced",0,0,100,100)])
        with self.assertRaises(ProviderConfigError):
            ProviderCatalogue([ModelPolicy("openai","unimplemented",1,1,100,100)])
