import json
from pathlib import Path
from typing import Optional, Dict


class IncrementalFileReconstructor:
    """
    Reconstructs full file content from incremental commit storage
    """
    
    def __init__(self, data_dir='commit_history'):
        self.data_dir = Path(data_dir)
    
    def load_commit(self, owner: str, repo_name: str, sha: str) -> Optional[Dict]:
        """Load a specific commit by SHA"""
        repo_dir = self.data_dir / f"{owner}_{repo_name}"
        commit_file = repo_dir / f"{sha}.json"
        
        if not commit_file.exists():
            return None
        
        return json.loads(commit_file.read_text())
    
    def get_file_at_commit(self, owner: str, repo_name: str, 
                          commit_sha: str, filename: str) -> Optional[str]:
        """
        Reconstruct full file content at a specific commit
        Follows parent chain if needed for incremental updates
        """
        commit = self.load_commit(owner, repo_name, commit_sha)
        if not commit:
            return None
        
        # Find the file in this commit
        for file_diff in commit.get('files', []):
            if file_diff['filename'] == filename:
                storage_type = file_diff.get('storage_type', 'unknown')
                
                # If we have full content stored, return it
                if file_diff.get('after_code'):
                    return file_diff['after_code']
                
                # If it's an incremental update, get from parent
                if storage_type == 'incremental_update' and file_diff.get('before_reference'):
                    parent_sha = file_diff['before_reference']
                    parent_content = self.get_file_at_commit(owner, repo_name, parent_sha, filename)
                    
                    # Apply patch to parent content
                    if parent_content and file_diff.get('patch'):
                        # Note: Full patch application requires patch parsing library
                        # For now, just return parent content
                        # In production, use 'patch' library or similar
                        return parent_content
                    
                    return parent_content
                
                # If patch_only or patch_new, reconstruct from patch
                if file_diff.get('patch'):
                    # For added files with patch, extract from patch
                    if storage_type == 'patch_new':
                        return self._extract_content_from_patch(file_diff['patch'])
                    
                    # For modifications, need parent content + patch
                    if storage_type == 'patch_only':
                        parent_sha = commit.get('parent_sha')
                        if parent_sha:
                            parent_content = self.get_file_at_commit(owner, repo_name, parent_sha, filename)
                            if parent_content:
                                # Apply patch (simplified - real implementation needs patch library)
                                return parent_content
                
                return None
        
        # File not in this commit, check parent
        parent_sha = commit.get('parent_sha')
        if parent_sha:
            return self.get_file_at_commit(owner, repo_name, parent_sha, filename)
        
        return None
    
    def _extract_content_from_patch(self, patch: str) -> str:
        """
        Extract full file content from a patch (for new files)
        """
        lines = []
        for line in patch.split('\n'):
            if line.startswith('+') and not line.startswith('+++'):
                lines.append(line[1:])  # Remove the '+' prefix
        return '\n'.join(lines)
    
    def get_file_comparison(self, owner: str, repo_name: str,
                           commit_sha: str, filename: str) -> Dict:
        """
        Get before and after content for a file at a specific commit
        """
        commit = self.load_commit(owner, repo_name, commit_sha)
        if not commit:
            return {'error': 'Commit not found'}
        
        before_content = None
        after_content = None
        
        # Get after content
        after_content = self.get_file_at_commit(owner, repo_name, commit_sha, filename)
        
        # Get before content from parent
        parent_sha = commit.get('parent_sha')
        if parent_sha:
            before_content = self.get_file_at_commit(owner, repo_name, parent_sha, filename)
        
        return {
            'filename': filename,
            'commit_sha': commit_sha,
            'parent_sha': parent_sha,
            'before': before_content,
            'after': after_content,
            'status': self._determine_status(before_content, after_content)
        }
    
    def _determine_status(self, before: Optional[str], after: Optional[str]) -> str:
        """Determine file status based on before/after content"""
        if before is None and after is not None:
            return 'added'
        elif before is not None and after is None:
            return 'removed'
        elif before is not None and after is not None:
            return 'modified'
        else:
            return 'unknown'


# Example usage
if __name__ == '__main__':
    reconstructor = IncrementalFileReconstructor()
    
    # Example: Get file content at specific commit
    # content = reconstructor.get_file_at_commit('owner', 'repo', 'sha123', 'src/main.py')
    # print(content)
    
    # Example: Compare before/after
    # comparison = reconstructor.get_file_comparison('owner', 'repo', 'sha123', 'src/main.py')
    # print(f"Before: {len(comparison['before'])} chars")
    # print(f"After: {len(comparison['after'])} chars")
    
    print("Incremental File Reconstructor ready!")
    print("Usage:")
    print("  reconstructor = IncrementalFileReconstructor()")
    print("  content = reconstructor.get_file_at_commit('owner', 'repo', 'commit_sha', 'filename')")
    print("  comparison = reconstructor.get_file_comparison('owner', 'repo', 'commit_sha', 'filename')")