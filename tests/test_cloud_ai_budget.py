import unittest
from cloud.ai_budget import amount,model_id

class TestBudgetValidation(unittest.TestCase):
    def test_cost_integer_only(self):
        for bad in (True,1.2,-1,0,10**15,"100"):
            with self.assertRaises(ValueError):
                amount(bad)
        self.assertEqual(amount(0,allow_zero=True),0)
    def test_provider_and_model(self):
        self.assertEqual(model_id("deepseek","deepseek-chat"),("deepseek","deepseek-chat"))
        for provider,model in (("custom","model"),("deepseek","https://evil.example"),("deepseek","x"*129)):
            with self.assertRaises(ValueError):
                model_id(provider,model)
