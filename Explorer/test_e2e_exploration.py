# File: test_e2e_exploration.py

import unittest
from explorer_agent import ExplorerAgent

class TestEndToEndExploration(unittest.TestCase):
    
    def test_full_exploration_flow_and_metrics_capture(self):
        """Tests the full agent loop on a real target, verifying scope and metrics."""
        
        # Use a public, simple, multi-page site for a controlled E2E test
        START_URL = "http://books.toscrape.com/"
        MAX_PAGES = 3
        
        agent = ExplorerAgent(START_URL, max_pages=MAX_PAGES)
        knowledge_base = agent.start_exploration()
        
        # 1. Scope and Visited Check
        self.assertTrue(len(knowledge_base) > 0)
        self.assertTrue(len(knowledge_base) <= MAX_PAGES)
        self.assertTrue(all(START_URL.split('//')[1].split('/')[0] in url for url in knowledge_base.keys())) # Domain check
        
        # 2. Metrics and Observability Check
        for url, data in knowledge_base.items():
            self.assertIn('metrics', data)
            metrics = data['metrics']
            self.assertIn('total_response_time_seconds', metrics)
            self.assertIn('tokens_consumed', metrics)
            self.assertTrue(metrics['total_response_time_seconds'] > 0)
            self.assertTrue(metrics['tokens_consumed'] >= 0)
            
            # 3. Knowledge Base Quality Check (Non-empty elements)
            self.assertTrue(data['llm_analysis']['elements'])
            self.assertTrue(data['elements'])

if __name__ == '__main__':
    unittest.main()