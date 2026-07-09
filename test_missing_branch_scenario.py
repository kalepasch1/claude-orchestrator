#!/usr/bin/env python3
"""
Test case to reproduce missing branch scenarios.
This test simulates what happens when a branch is missing from git but expected in the database.
"""
import os, sys, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

def create_test_missing_branch_scenario():
    """Create a test scenario that reproduces missing branch conditions."""
    
    print("=== Creating Missing Branch Test Scenario ===")
    
    # Get a project to work with
    projects = db.select("projects", {"select": "id,name,repo_path", "limit": 1}) or []
    if not projects:
        print("No projects found in database")
        return
    
    project = projects[0]
    project_id = project["id"]
    project_name = project["name"]
    repo_path = project["repo_path"]
    
    print(f"Testing with project: {project_name}")
    
    # Create a fake task that would trigger missing branch condition
    test_slug = "agent/test-missing-branch"
    
    # First, check if the branch exists in git
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"origin/{test_slug}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        branch_exists = result.returncode == 0
        print(f"Branch {test_slug} exists in git: {branch_exists}")
        
        # If it doesn't exist, simulate the condition
        if not branch_exists:
            print("Simulating missing branch condition...")
            
            # Create a task that references this non-existent branch
            try:
                db.insert("tasks", {
                    "project_id": project_id,
                    "slug": test_slug,
                    "prompt": "Test missing branch scenario",
                    "state": "QUEUED",
                    "created_at": "now()"
                })
                print(f"Created task for missing branch: {test_slug}")
                
                # Create an approval card that would be processed by merge train
                db.insert("approvals", {
                    "project": project_id,
                    "slug": test_slug,
                    "title": f"Merge of {test_slug}",
                    "kind": "integrate",
                    "status": "approved",
                    "decided_by": "canonical-train",
                    "created_at": "now()"
                })
                print(f"Created approval card for missing branch: {test_slug}")
                
            except Exception as e:
                print(f"Error creating test scenario: {e}")
                
    except Exception as e:
        print(f"Error checking branch existence: {e}")

def simulate_merge_train_missing_branch():
    """Simulate what happens in merge_train when a branch is missing."""
    
    print("\n=== Simulating Merge Train Missing Branch Handling ===")
    
    # This simulates the logic from merge_train.py _integrate_card function
    try:
        # Get an approved card that references a missing branch
        cards = db.select("approvals", {
            "select": "*",
            "status": "eq.approved",
            "kind": "eq.integrate",
            "limit": 5
        }) or []
        
        if not cards:
            print("No approved integrate cards found for simulation")
            return
            
        print(f"Found {len(cards)} approved integrate cards to simulate")
        
        # Check each card for missing branch conditions
        for i, card in enumerate(cards[:3]):  # Limit to first 3
            slug = card.get("slug", "")
            if not slug:
                continue
                
            print(f"\nSimulating card {i+1}: {slug}")
            
            # This is what happens in merge_train when branch is missing
            # It would set decided_by to "train:no-repo" or similar
            print(f"  Would check if branch 'agent/{slug}' exists")
            print(f"  If missing, would set decided_by to 'train:waiting-branch' or 'train:branch-missing'")
            
    except Exception as e:
        print(f"Error in simulation: {e}")

if __name__ == "__main__":
    create_test_missing_branch_scenario()
    simulate_merge_train_missing_branch()
