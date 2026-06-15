import urllib.request, re, json

url = 'https://takeuforward.org/strivers-a2z-dsa-course/strivers-a2z-dsa-course-sheet-2/'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    html = urllib.request.urlopen(req).read().decode('utf-8')
    slugs = set(re.findall(r'leetcode\.com/problems/([^/\"\'\?]+)', html))
    print('Found slugs:', len(slugs))
    if len(slugs) > 10:
        d = {s: i+1 for i, s in enumerate(sorted(slugs))}
        with open('roadmaps/striver_a2z.json', 'w') as f:
            json.dump(d, f, indent=4)
        print('Written to roadmaps/striver_a2z.json')
except Exception as e:
    print('Error:', e)
