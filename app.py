from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import json
from datetime import datetime
import hmac
import hashlib
import os
from pathlib import Path
from github_monitor import GitHubMonitor
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')
monitor = GitHubMonitor()

DATA_DIR = Path('commit_history')
REPOS_FILE = DATA_DIR / 'repositories.json'

def init_storage():
    DATA_DIR.mkdir(exist_ok=True)
    if not REPOS_FILE.exists():
        REPOS_FILE.write_text('{}')

init_storage()

def load_repos():
    return json.loads(REPOS_FILE.read_text())

def save_repos(repos):
    REPOS_FILE.write_text(json.dumps(repos, indent=2))

def get_repo_dir(owner, repo_name):
    repo_dir = DATA_DIR / f"{owner}_{repo_name}"
    repo_dir.mkdir(exist_ok=True)
    return repo_dir

def save_commit_history(owner, repo_name, commit_data):
    repo_dir = get_repo_dir(owner, repo_name)
    sha = commit_data['commit_sha']
    commit_file = repo_dir / f"{sha}.json"
    commit_file.write_text(json.dumps(commit_data, indent=2))

def load_commit_history(owner, repo_name):
    repo_dir = get_repo_dir(owner, repo_name)
    commits = []
    for commit_file in sorted(repo_dir.glob('*.json'), key=lambda x: x.stat().st_mtime, reverse=True):
        commits.append(json.loads(commit_file.read_text()))
    return commits

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/submit-repo', methods=['POST'])
def submit_repo():
    data = request.json
    repo_url = data.get('repo_url', '').strip()
    
    parts = repo_url.rstrip('/').split('/')
    owner = parts[-2]
    repo_name = parts[-1]
    
    repos = load_repos()
    repo_key = f"{owner}/{repo_name}"
    
    if repo_key in repos:
        return jsonify({'message': 'Repository already added'})
    
    public_url = request.host_url.rstrip('/') + '/webhook'
    webhook_id = monitor.create_webhook(owner, repo_name, public_url)
    
    repos[repo_key] = {
        'repo_url': repo_url,
        'owner': owner,
        'repo_name': repo_name,
        'webhook_id': webhook_id,
        'created_at': datetime.now().isoformat()
    }
    
    save_repos(repos)
    get_repo_dir(owner, repo_name)
    
    return jsonify({'message': 'Repository added with webhook'})

@app.route('/webhook', methods=['POST'])
def github_webhook():
    print("🔥 Webhook hit")
    
    raw_body = request.get_data()
    
    signature = request.headers.get('X-Hub-Signature-256')
    if WEBHOOK_SECRET:
        if not signature or not verify_signature(raw_body, signature):
            print("❌ Invalid signature")
            return '', 401
    
    payload = request.get_json(silent=True)
    if not payload:
        print("❌ Empty or invalid JSON")
        return '', 200
    
    event_type = request.headers.get('X-GitHub-Event')
    if event_type != 'push':
        print(f"Ignored event: {event_type}")
        return '', 200
    
    repo_info = payload.get('repository', {})
    full_name = repo_info.get('full_name')
    
    if not full_name or '/' not in full_name:
        print("❌ Invalid repository info")
        return '', 200
    
    owner, repo_name = full_name.split('/')
    commits = payload.get('commits', [])
    
    if not commits:
        print("No commits in payload")
        return '', 200
    
    print(f"📦 Processing {len(commits)} commits for {owner}/{repo_name}")
    
    repos = load_repos()
    repo_key = f"{owner}/{repo_name}"
    
    if repo_key not in repos:
        print("❌ Repo not registered")
        return '', 200
    
    for commit in commits:
        sha = commit.get('id')
        if not sha:
            continue
        
        try:
            event, file_diffs, parent_sha = monitor.analyze_commit(owner, repo_name, sha)
            if not event:
                continue
            
            commit_data = {
                'commit_sha': sha,
                'parent_sha': parent_sha,
                'timestamp': datetime.now().isoformat(),
                'message': commit.get('message', ''),
                'author': commit.get('author', {}),
                'event': {
                    'type': event['type'],
                    'description': event['description'],
                    'files_changed': event['files_changed'],
                    'total_additions': event.get('total_additions', 0),
                    'total_deletions': event.get('total_deletions', 0)
                },
                'files': file_diffs
            }
            
            save_commit_history(owner, repo_name, commit_data)
            
        except Exception as e:
            print(f"Error processing commit {sha}: {e}")
    
    print("✅ Webhook processed successfully")
    return '', 200

def verify_signature(raw_body, signature):
    mac = hmac.new(
        WEBHOOK_SECRET.encode(),
        msg=raw_body,
        digestmod=hashlib.sha256
    )
    expected = "sha256=" + mac.hexdigest()
    return hmac.compare_digest(expected, signature)

@app.route('/api/repos', methods=['GET'])
def get_repos():
    repos = load_repos()
    return jsonify([{
        'id': idx,
        'repo_url': data['repo_url'],
        'owner': data['owner'],
        'repo_name': data['repo_name'],
        'webhook_active': data.get('webhook_id') is not None,
        'created_at': data['created_at']
    } for idx, (key, data) in enumerate(repos.items())])

@app.route('/api/events/<owner>/<repo_name>', methods=['GET'])
def get_events(owner, repo_name):
    commits = load_commit_history(owner, repo_name)
    return jsonify([{
        'commit_sha': c['commit_sha'],
        'parent_sha': c.get('parent_sha'),
        'event_type': c['event']['type'],
        'description': c['event']['description'],
        'files_changed': c['event']['files_changed'],
        'timestamp': c['timestamp']
    } for c in commits[:50]])

@app.route('/api/commit/<owner>/<repo_name>/<sha>', methods=['GET'])
def get_commit_details(owner, repo_name, sha):
    repo_dir = get_repo_dir(owner, repo_name)
    commit_file = repo_dir / f"{sha}.json"
    
    if not commit_file.exists():
        return jsonify({'error': 'Commit not found'}), 404
    
    return jsonify(json.loads(commit_file.read_text()))

@app.route('/api/all-events', methods=['GET'])
def get_all_events():
    repos = load_repos()
    all_events = []
    
    for repo_key, repo_data in repos.items():
        owner = repo_data['owner']
        repo_name = repo_data['repo_name']
        commits = load_commit_history(owner, repo_name)
        
        for commit in commits:
            all_events.append({
                'commit_sha': commit['commit_sha'],
                'parent_sha': commit.get('parent_sha'),
                'event_type': commit['event']['type'],
                'description': commit['event']['description'],
                'files_changed': commit['event']['files_changed'],
                'timestamp': commit['timestamp'],
                'repo_name': repo_name,
                'owner': owner
            })
    
    all_events.sort(key=lambda x: x['timestamp'], reverse=True)
    return jsonify(all_events[:100])

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)