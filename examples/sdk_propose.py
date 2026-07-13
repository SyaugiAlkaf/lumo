from amanah import AmanahClient

client = AmanahClient()
decision = client.propose(open("tests/fixtures/invoices/clean_in_policy.txt").read())
print(decision.decision, decision.codes)
print(client.status(decision.intent_id))
