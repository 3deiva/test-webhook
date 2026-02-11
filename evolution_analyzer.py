import json
from pathlib import Path
import difflib
from typing import Dict, List


class CommitEvolutionAnalyzer:
    """
    Analyzes commit evolution patterns using stored JSON history
    """
    
    def __init__(self, data_dir='commit_history'):
        self.data_dir = Path(data_dir)
    
    def load_repo_commits(self, owner: str, repo_name: str) -> List[Dict]:
        """Load all commits for a repository in chronological order"""
        repo_dir = self.data_dir / f"{owner}_{repo_name}"
        if not repo_dir.exists():
            return []
        
        commits = []
        for commit_file in repo_dir.glob('*.json'):
            with open(commit_file) as f:
                commits.append(json.load(f))
        
        # Sort by timestamp
        commits.sort(key=lambda x: x['timestamp'])
        return commits
    
    def analyze_code_similarity(self, file_diff: Dict) -> Dict:
        """
        Determine what kind of change occurred
        Handles both patch-only and full code storage
        """
        status = file_diff['status']
        patch = file_diff.get('patch', '')
        before_code = file_diff.get('before_code')
        after_code = file_diff.get('after_code')
        
        if status == 'added':
            return {'type': 'new_file', 'similarity': 0.0, 'has_full_code': after_code is not None}
        
        if status == 'removed':
            return {'type': 'deleted_file', 'similarity': 0.0, 'has_full_code': False}
        
        # If we have full code, do deep analysis
        if before_code and after_code:
            similarity = difflib.SequenceMatcher(None, before_code, after_code).ratio()
            
            # Remove whitespace and compare
            before_stripped = ''.join(before_code.split())
            after_stripped = ''.join(after_code.split())
            logic_similarity = difflib.SequenceMatcher(None, before_stripped, after_stripped).ratio()
            
            if similarity > 0.95:
                return {'type': 'minor_changes', 'similarity': similarity, 'has_full_code': True}
            elif logic_similarity > 0.95 and similarity < 0.95:
                return {'type': 'formatting_only', 'similarity': similarity, 'logic_similarity': logic_similarity, 'has_full_code': True}
            elif logic_similarity > 0.80:
                return {'type': 'refactoring', 'similarity': similarity, 'logic_similarity': logic_similarity, 'has_full_code': True}
            else:
                return {'type': 'major_rewrite', 'similarity': similarity, 'logic_similarity': logic_similarity, 'has_full_code': True}
        
        # If only patch available, analyze patch size
        else:
            patch_size = len(patch)
            additions = file_diff.get('additions', 0)
            deletions = file_diff.get('deletions', 0)
            
            if patch_size < 200:
                return {'type': 'small_change', 'patch_size': patch_size, 'has_full_code': False}
            elif additions > deletions * 2:
                return {'type': 'expansion', 'additions': additions, 'deletions': deletions, 'has_full_code': False}
            elif deletions > additions * 2:
                return {'type': 'reduction', 'additions': additions, 'deletions': deletions, 'has_full_code': False}
            else:
                return {'type': 'modification', 'patch_size': patch_size, 'has_full_code': False}
    
    def detect_development_pattern(self, commits: List[Dict]) -> Dict:
        """
        Determine if development was gradual or bulk upload
        """
        if not commits:
            return {'pattern': 'no_commits'}
        
        total_files = sum(c['event']['files_changed'] for c in commits)
        avg_files_per_commit = total_files / len(commits)
        
        # Check for bulk uploads (large initial commits)
        first_commit = commits[0]
        first_commit_files = first_commit['event']['files_changed']
        first_commit_ratio = first_commit_files / total_files if total_files > 0 else 0
        
        if first_commit_ratio > 0.7:
            return {
                'pattern': 'bulk_upload',
                'first_commit_percentage': f"{first_commit_ratio * 100:.1f}%",
                'total_commits': len(commits)
            }
        elif avg_files_per_commit < 5:
            return {
                'pattern': 'gradual_development',
                'avg_files_per_commit': f"{avg_files_per_commit:.1f}",
                'total_commits': len(commits)
            }
        else:
            return {
                'pattern': 'mixed_development',
                'avg_files_per_commit': f"{avg_files_per_commit:.1f}",
                'total_commits': len(commits)
            }
    
    def analyze_file_evolution(self, filename: str, commits: List[Dict]) -> List[Dict]:
        """
        Track how a specific file evolved across commits
        """
        evolution = []
        
        for commit in commits:
            for file_diff in commit.get('files', []):
                if file_diff['filename'] == filename:
                    analysis = self.analyze_code_similarity(file_diff)
                    
                    before_lines = 0
                    after_lines = 0
                    
                    # Count lines if full code available
                    if file_diff.get('before_code'):
                        before_lines = len(file_diff['before_code'].splitlines())
                    if file_diff.get('after_code'):
                        after_lines = len(file_diff['after_code'].splitlines())
                    
                    evolution.append({
                        'commit_sha': commit['commit_sha'],
                        'parent_sha': commit.get('parent_sha'),
                        'timestamp': commit['timestamp'],
                        'message': commit['message'],
                        'status': file_diff['status'],
                        'change_type': analysis['type'],
                        'additions': file_diff.get('additions', 0),
                        'deletions': file_diff.get('deletions', 0),
                        'lines_before': before_lines,
                        'lines_after': after_lines,
                        'has_full_code': analysis.get('has_full_code', False)
                    })
        
        return evolution
    
    def generate_report(self, owner: str, repo_name: str) -> Dict:
        """
        Generate comprehensive evolution report for a repository
        """
        commits = self.load_repo_commits(owner, repo_name)
        
        if not commits:
            return {'error': 'No commits found'}
        
        # Overall development pattern
        dev_pattern = self.detect_development_pattern(commits)
        
        # Analyze each file's evolution
        all_files = set()
        for commit in commits:
            for file_diff in commit.get('files', []):
                all_files.add(file_diff['filename'])
        
        file_analyses = {}
        for filename in all_files:
            file_analyses[filename] = self.analyze_file_evolution(filename, commits)
        
        # Event type distribution
        event_types = {}
        for commit in commits:
            event_type = commit['event']['type']
            event_types[event_type] = event_types.get(event_type, 0) + 1
        
        # Storage efficiency stats
        total_files_analyzed = 0
        files_with_full_code = 0
        
        for commit in commits:
            for file_diff in commit.get('files', []):
                total_files_analyzed += 1
                if file_diff.get('before_code') or file_diff.get('after_code'):
                    files_with_full_code += 1
        
        storage_efficiency = {
            'total_file_changes': total_files_analyzed,
            'full_code_stored': files_with_full_code,
            'patch_only': total_files_analyzed - files_with_full_code,
            'efficiency_percentage': f"{((total_files_analyzed - files_with_full_code) / total_files_analyzed * 100):.1f}%" if total_files_analyzed > 0 else "0%"
        }
        
        return {
            'repository': f"{owner}/{repo_name}",
            'total_commits': len(commits),
            'development_pattern': dev_pattern,
            'event_distribution': event_types,
            'total_files_touched': len(all_files),
            'storage_efficiency': storage_efficiency,
            'file_evolutions': file_analyses,
            'timeline': [
                {
                    'sha': c['commit_sha'][:7],
                    'parent_sha': c.get('parent_sha', '')[:7] if c.get('parent_sha') else None,
                    'timestamp': c['timestamp'],
                    'type': c['event']['type'],
                    'description': c['event']['description']
                }
                for c in commits
            ]
        }


# Example usage
if __name__ == '__main__':
    analyzer = CommitEvolutionAnalyzer()
    
    # Replace with actual owner/repo
    # report = analyzer.generate_report('owner', 'repo_name')
    # print(json.dumps(report, indent=2))
    
    print("Evolution Analyzer ready!")
    print("Usage:")
    print("  analyzer = CommitEvolutionAnalyzer()")
    print("  report = analyzer.generate_report('owner', 'repo_name')")
    print("  print(json.dumps(report, indent=2))")
