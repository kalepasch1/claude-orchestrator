#!/usr/bin/env python3
"""
Diagnostic tool for missing branch analysis.
This script analyzes the merge-train pressure state and identifies root causes of missing branches.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

def analyze_missing_branches():
    """Analyze missing branch issues across projects."""
    
    # Get all projects
    projects = db.select("projects") or []
    project_map = {p["id"]: p for p in projects}
    
    print("=== Missing Branch Diagnostic Analysis ===")
    
    # Check merge-train pressure data
    try:
        pressure_rows = db.select("controls", {"select": "key,value", "key": "eq.merge_train_pressure"})
        if pressure_rows:
            pressure_data = json.loads(pressure_rows[0]["value"])
            print("\n--- Merge Train Pressure Data ---")
            for project_name, stats in pressure_data["projects"].items():
                print(f"Project: {project_name}")
                print(f"  Passed waiting: {stats['passed_waiting']}")
                print(f"  Missing branch: {stats['missing_branch']}")
                print(f"  Oldest wait age (s): {stats['oldest_wait_age_s']}")
                print(f"  Risk breakdown: low={stats['risk']['low']}, standard={stats['standard']}, sensitive={stats['sensitive']}")
    except Exception as e:
        print(f"Could not fetch pressure data: {e}")
    
    # Check for tasks with missing branches
    print("\n--- Tasks with Missing Branch Indicators ---")
    try:
        # Look for tasks that might be in a state indicating missing branches
        tasks = db.select("tasks", {
            "select": "id,slug,project_id,state,note",
            "order": "created_at.desc",
            "limit": 50
        }) or []
        
        missing_branch_tasks = []
        for task in tasks:
            note = task.get("note", "").lower()
            if any(keyword in note for keyword in ["missing", "branch", "rebuild", "redo"]):
                missing_branch_tasks.append(task)
        
        print(f"Found {len(missing_branch_tasks)} tasks with potential branch issues:")
        for task in missing_branch_tasks[:10]:  # Show first 10
            project_name = project_map.get(task["project_id"], {}).get("name", "unknown")
            print(f"  Task {task['id']}: {task['slug']} ({project_name}) - {task['note'][:100]}...")
            
    except Exception as e:
        print(f"Could not analyze tasks: {e}")
    
    # Check for approval cards with missing branches
    print("\n--- Approval Cards with Missing Branch Indicators ---")
    try:
        approvals = db.select("approvals", {
            "select": "id,slug,title,status,decided_by,kind",
            "order": "created_at.desc",
            "limit": 50
        }) or []
        
        missing_branch_approvals = []
        for approval in approvals:
            decided_by = approval.get("decided_by", "")
            if "missing" in decided_by.lower() or "no-repo" in decided_by.lower():
                missing_branch_approvals.append(approval)
        
        print(f"Found {len(missing_branch_approvals)} approval cards with missing branch indicators:")
        for approval in missing_branch_approvals[:10]:  # Show first 10
            print(f"  Card {approval['id']}: {approval['slug']} - {approval['decided_by']}")
            
    except Exception as e:
        print(f"Could not analyze approvals: {e}")

def check_branch_consistency():
    """Check consistency between database records and actual git branches."""
    print("\n=== Branch Consistency Check ===")
    
    # Get projects with repo paths
    projects = db.select("projects", {"select": "id,name,repo_path"}) or []
    
    for project in projects:
        project_id = project["id"]
        project_name = project["name"]
        repo_path = project["repo_path"]
        
        if not repo_path or not os.path.isdir(repo_path):
            print(f"Project {project_name}: Repo path missing or invalid")
            continue
            
        try:
            # Check for agent branches in the project
            import subprocess
            result = subprocess.run(
                ["git", "branch", "-r"], 
                cwd=repo_path, 
                capture_output=True, 
                text=True, 
                timeout=30
            )
            
            if result.returncode == 0:
                remote_branches = result.stdout.strip().split('\n')
                agent_branches = [b for b in remote_branches if b.startswith('origin/agent/')]
                
                print(f"Project {project_name}: Found {len(agent_branches)} agent branches")
                
                # Check tasks that should have corresponding branches
                tasks = db.select("tasks", {
                    "select": "id,slug,state",
                    "project_id": f"eq.{project_id}",
                    "slug": "like.agent/%"
                }) or []
                
                print(f"  Project {project_name}: Found {len(tasks)} agent-related tasks")
                
            else:
                print(f"Project {project_name}: Could not list remote branches")
                
        except Exception as e:
            print(f"Project {project_name}: Error checking branches - {e}")

if __name__ == "__main__":
    analyze_missing_branches()
    check_branch_consistency()
