import requests
from typing import Dict, List, Tuple
import os
import base64


class GitHubMonitor:
    """
    Monitors GitHub repositories using webhooks
    Advanced commit analysis with before/after code capture
    """

    def __init__(self):
        self.token = os.getenv('GITHUB_TOKEN')
        self.headers = {}
        if self.token:
            self.headers['Authorization'] = f'token {self.token}'

    # ------------------- GitHub API helpers -------------------

    def get_commit_details(self, owner: str, repo: str, sha: str) -> Dict:
        url = f'https://api.github.com/repos/{owner}/{repo}/commits/{sha}'
        r = requests.get(url, headers=self.headers, timeout=15)
        return r.json() if r.status_code == 200 else {}

    def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        """
        Fetch file content at specific commit (before/after)
        """
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={ref}"
        r = requests.get(url, headers=self.headers, timeout=15)

        if r.status_code == 200:
            content = r.json().get('content', '')
            try:
                return base64.b64decode(content).decode('utf-8', errors='ignore')
            except:
                return ""
        return ""

    # ------------------- Webhook creation -------------------

    def create_webhook(self, owner: str, repo: str, webhook_url: str):
        url = f'https://api.github.com/repos/{owner}/{repo}/hooks'

        payload = {
            "name": "web",
            "active": True,
            "events": ["push"],
            "config": {
                "url": webhook_url,
                "content_type": "json",
                "secret": os.getenv('WEBHOOK_SECRET')
            }
        }

        requests.post(url, json=payload, headers=self.headers)

    # ------------------- MAIN ANALYZER -------------------

    def analyze_commit(self, owner: str, repo: str, sha: str) -> Tuple[Dict, List[Dict], str]:
        commit = self.get_commit_details(owner, repo, sha)
        if not commit:
            return {}, [], None

        files = commit.get('files', [])
        stats = commit.get('stats', {})
        message = commit.get('commit', {}).get('message', '')

        parent_sha = None
        if commit.get('parents'):
            parent_sha = commit['parents'][0]['sha']

        # -------- Smart file diff collection (patch-first strategy) --------
        file_diffs = []

        for f in files:
            path = f['filename']
            status = f['status']
            patch = f.get('patch', '')
            additions = f.get('additions', 0)
            deletions = f.get('deletions', 0)
            changes = f.get('changes', 0)

            file_diff = {
                'filename': path,
                'status': status,
                'additions': additions,
                'deletions': deletions,
                'changes': changes,
                'patch': patch
            }

            # Decide if we need full file content
            patch_size = len(patch)
            needs_full_file = patch_size > 800

            if status == 'added':
                # For new files, patch contains full content if small
                if needs_full_file:
                    file_diff['after_code'] = self.get_file_content(owner, repo, path, sha)
                else:
                    file_diff['after_code'] = None  # Patch is enough
                file_diff['before_code'] = None

            elif status == 'removed':
                # Deleted files - don't fetch anything
                file_diff['before_code'] = None
                file_diff['after_code'] = None

            elif status == 'modified':
                # Only fetch full files for large patches
                if needs_full_file:
                    file_diff['before_code'] = self.get_file_content(owner, repo, path, parent_sha) if parent_sha else None
                    file_diff['after_code'] = self.get_file_content(owner, repo, path, sha)
                else:
                    file_diff['before_code'] = None
                    file_diff['after_code'] = None

            elif status == 'renamed':
                # Renamed files with changes
                if needs_full_file:
                    file_diff['after_code'] = self.get_file_content(owner, repo, path, sha)
                    file_diff['before_code'] = None
                else:
                    file_diff['before_code'] = None
                    file_diff['after_code'] = None

            file_diffs.append(file_diff)

        # -------- Classification --------
        files_changed = len(files)
        additions = stats.get('additions', 0)
        deletions = stats.get('deletions', 0)

        file_analysis = self._analyze_files(files)
        event_type, description = self._classify_work(
            file_analysis, files_changed, additions, deletions, message
        )

        event = {
            'type': event_type,
            'description': description,
            'files_changed': files_changed,
            'total_additions': additions,
            'total_deletions': deletions
        }

        return event, file_diffs, parent_sha

    # ------------------- Your original smart logic -------------------

    def _analyze_files(self, files: List[Dict]) -> Dict:
        analysis = {
            'new_files': 0,
            'deleted_files': 0,
            'modified_files': 0,
            'extensions': {},
            'directories': set(),
            'has_dependencies': False,
            'has_config': False,
            'has_docs': False,
            'has_tests': False,
            'large_changes': 0
        }

        dependency_files = [
            'package.json', 'requirements.txt', 'pom.xml', 'build.gradle',
            'Gemfile', 'Cargo.toml', 'go.mod', 'composer.json',
            'package-lock.json', 'yarn.lock'
        ]

        config_files = [
            '.env', 'config.json', 'config.yaml', 'settings.py',
            'webpack.config.js', 'tsconfig.json', '.gitignore'
        ]

        for file in files:
            filename = file['filename']
            status = file['status']
            changes = file.get('changes', 0)

            if status == 'added':
                analysis['new_files'] += 1
            elif status == 'removed':
                analysis['deleted_files'] += 1
            else:
                analysis['modified_files'] += 1

            if '.' in filename:
                ext = filename.split('.')[-1]
                analysis['extensions'][ext] = analysis['extensions'].get(ext, 0) + 1

            if '/' in filename:
                directory = filename.split('/')[0]
                analysis['directories'].add(directory)

            if any(dep in filename.lower() for dep in dependency_files):
                analysis['has_dependencies'] = True

            if any(cfg in filename.lower() for cfg in config_files):
                analysis['has_config'] = True

            if 'readme' in filename.lower() or filename.endswith('.md'):
                analysis['has_docs'] = True

            if 'test' in filename.lower() or 'spec' in filename.lower():
                analysis['has_tests'] = True

            if changes > 100:
                analysis['large_changes'] += 1

        return analysis

    def _classify_work(self, analysis: Dict, files_changed: int,
                       additions: int, deletions: int, message: str):

        if analysis['has_dependencies']:
            return ('dependency_update', f'Dependency update ({files_changed} files)')

        if len(analysis['directories']) > 1 and analysis['new_files'] > 3:
            return ('new_module', f'New module added ({analysis["new_files"]} new files)')

        if analysis['has_config'] and files_changed <= 3:
            return ('config_change', 'Configuration update')

        if analysis['has_docs'] and files_changed <= 2:
            return ('documentation', 'Documentation update')

        if analysis['has_tests']:
            return ('testing', f'Test files updated ({files_changed} files)')

        if deletions > additions and deletions > 200:
            return ('refactor', f'Code refactoring ({deletions} lines removed)')

        if additions > 300:
            return ('major_feature', f'Major feature update (+{additions} lines)')

        if analysis['new_files'] > 0:
            return ('files_added', f'{analysis["new_files"]} new files added')

        if analysis['deleted_files'] > 0:
            return ('cleanup', f'{analysis["deleted_files"]} files removed')

        if any(k in message.lower() for k in ['fix', 'bug', 'patch']):
            return ('bug_fix', f'Bug fix ({files_changed} files)')

        if any(k in message.lower() for k in ['feat', 'feature', 'add']):
            return ('feature', f'Feature implementation ({files_changed} files)')

        if files_changed <= 2 and additions < 50:
            return ('minor_update', f'Minor update ({files_changed} files)')

        return ('major_update', f'Major update ({files_changed} files)')