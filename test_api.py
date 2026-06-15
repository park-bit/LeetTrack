import urllib.request, json
url = 'https://leetcode.com/graphql'
query = '''
query userProfileUserQuestionProgress($userSlug: String!) {
  userProfileUserQuestionProgress(userSlug: $userSlug) {
    numAcceptedQuestions
    numFailedQuestions
    numUntouchedQuestions
  }
}
'''
req = urllib.request.Request(url, headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}, data=json.dumps({'query': query, 'variables': {'userSlug': 'park-bit'}}).encode('utf-8'))
try:
    res = json.loads(urllib.request.urlopen(req).read().decode('utf-8'))
    print(json.dumps(res, indent=2))
except Exception as e:
    print('Error:', e)
