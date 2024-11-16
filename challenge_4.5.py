import http.client

host = 'jooble.org'
key = 'eeac8c87-9569-4de0-813a-3884f3177633'

connection = http.client.HTTPConnection(host)
#request headers
headers = {"Content-type": "application/json"}
#json query
body = '{ "keywords": "it", "location": "Bern"}'
connection.request('POST','/api/' + key, body, headers)
response = connection.getresponse()
print(response.status, response.reason)
print(response.read())