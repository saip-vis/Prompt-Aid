"""Deliberately flawed starting code for a fictional creator-operations demo.

Input: JSON array of {id, body}; output: a JSON array of extracted offers.
No external services, real creators, or email sending.
"""
import json
import re
import sys


def extract(message):
    body = message['body']
    money = re.search(r'(USD|EUR|GBP|CAD|\$)\s*([\d,]+)', body)
    date = re.search(r'\d{4}-\d{2}-\d{2}', body)
    deliverables = re.findall(r'\d+ (?:Instagram reels?|Instagram stories|TikTok videos?|YouTube shorts?)', body)
    # These defaults and first-match choices are intentionally unsafe.
    return {'id': message['id'], 'budget': int(money[2].replace(',', '')) if money else 2500,
            'currency': money[1] if money and money[1] != '$' else 'USD',
            'deadline': date[0] if date else '2026-12-31', 'deliverables': deliverables,
            'needs_review': False,
            'evidence': {'budget': money[0] if money else None,
                         'currency': money[0] if money else None,
                         'deadline': date[0] if date else None,
                         'deliverables': deliverables}}


if __name__ == '__main__':
    with open(sys.argv[1]) as source:
        print(json.dumps([extract(message) for message in json.load(source)]))
