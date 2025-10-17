# main.py
import os
import time
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, HttpUrl
from dotenv import load_dotenv
from typing import List, Dict, Any
import requests
from github import Github
import base64

# --- Load Environment Variables ---
load_dotenv()
MY_SECRET = os.getenv("STUDENT_SECRET")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME") # Add your GitHub username to .env

app = FastAPI()

# --- Pydantic Models for Data Validation ---
class TaskRequest(BaseModel):
    email: str
    secret: str
    task: str
    round: int
    nonce: str
    brief: str
    checks: List[str]
    evaluation_url: HttpUrl
    attachments: List[Dict[str, Any]]

def generate_code_with_llm(brief: str, checks: list, attachments: list) -> str:
    """
    Generates HTML by instructing the LLM to directly embed attachment data URIs.
    This is the correct approach for creating a single, self-contained HTML file.
    """
    print("🤖 Calling aipipe.org API to generate code...")
    api_key = os.getenv("AIPIPE_TOKEN")
    if not api_key:
        print("❌ AIPIPE_TOKEN not found in environment variables.")
        return "<h1>Error: AIPIPE_TOKEN is not configured.</h1>"

    url = "https://aipipe.org/openai/v1/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # --- Create attachments context with instructions to embed the data URI ---
    attachments_context = ""
    if attachments:
        attachments_context += "\n\nThe following file attachments are provided as data URIs. **Do not decode or process the Base64 content.** You must embed the entire data URI string directly into the appropriate HTML tags.\n"
        attachments_context += "For example, for an image named 'sample.png', you would generate a tag like: <img src=\"data:image/png;base64,iVBORw...\">\n"
        for attachment in attachments:
            file_name = attachment.get("name", "unknown_file")
            data_uri = attachment.get("url", "")
            attachments_context += f"\n--- FILE: {file_name} ---\n{data_uri}\n--- END FILE ---\n"

    # --- The final, optimized prompt ---
    prompt = f"""
    You are an expert front-end web developer. Your task is to generate a single, complete, self-contained HTML file.
    All CSS, JavaScript, and other assets must be included directly within the HTML file.

    The user's application brief is:
    ---
    {brief}
    ---
    {attachments_context}
    The generated page must be able to pass these automated checks:
    ---
    {', '.join(checks)}
    ---

    Respond with only the raw HTML code and nothing else.
    """
    
    payload = {"model": "gpt-4o", "input": prompt}

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        response_data = response.json()
        code = response_data["output"][0]["content"][0]["text"].strip()
        
        # Cleanup logic remains the same
        if code.startswith("```"):
            code = code.split('\n', 1)[1]
        if code.endswith("```"):
            code = '\n'.join(code.split('\n')[:-1])
            
        print("✅ LLM code generation successful.")
        return code
        
    except Exception as e:
        print(f"❌ LLM generation failed: {e}")
        return f"<h1>Error: Could not generate code.</h1><p>{e}</p>"

# --- Constants for files ---
MIT_LICENSE = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

def enable_github_pages(repo_full_name: str, token: str):
    """
    Enables GitHub Pages for a repository using the GitHub REST API.
    """
    print("🌍 Enabling GitHub Pages...")
    url = f"https://api.github.com/repos/{repo_full_name}/pages"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    
    # This payload tells GitHub to build Pages from the root ("/") of the "main" branch
    payload = {
        "source": {
            "branch": "main",
            "path": "/"
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()  # Raises an exception for HTTP error codes
        
        if response.status_code == 201: # 201 Created is the success code
            print("✅ GitHub Pages enabled successfully.")
            return True
        else:
            print(f"⚠️  Unexpected status code while enabling Pages: {response.status_code}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to enable GitHub Pages: {e}")
        print(f"Response: {e.response.text if e.response else 'No response'}")
        return False

def create_and_push_to_github(repo_name: str, html_content: str, brief: str, attachments: list) -> (str, str):
    """
    Creates a GitHub repo, pushes files (including attachments), enables Pages, and returns the repo URL and commit SHA.
    """
    repo = None
    try:
        print(f"🐙 Accessing GitHub...")
        github_pat = os.getenv("GITHUB_PAT")
        # ... (rest of the authentication logic) ...
        g = Github(github_pat)
        user = g.get_user()
        print(f"✓ Authenticated as: {user.login}")

        print(f"Creating new repository: {repo_name}...")
        repo = user.create_repo(repo_name, private=False)
        print(f"✓ Repository created: {repo.html_url}")

        readme_content = f"# {repo_name}\n\nThis project was auto-generated based on the brief: '{brief}'"

        # Create the primary files
        repo.create_file("index.html", "feat: initial commit", html_content, branch="main")
        repo.create_file("LICENSE", "feat: add MIT license", MIT_LICENSE, branch="main")
        commit_info = repo.create_file("README.md", "feat: add readme", readme_content, branch="main")

        # --- NEW: Process and create files from attachments ---
        if attachments:
            print("📎 Processing attachments...")
            for attachment in attachments:
                file_name = attachment.get("name")
                data_uri = attachment.get("url")
                if not file_name or not data_uri:
                    continue
                try:
                    header, encoded_data = data_uri.split(",", 1)
                    decoded_content = base64.b64decode(encoded_data)
                    print(f"   Creating attachment file: {file_name}...")
                    repo.create_file(file_name, f"feat: add attachment {file_name}", decoded_content, branch="main")
                except Exception as e:
                    print(f"⚠️  Could not process attachment {file_name}: {e}")
        
        commit = commit_info["commit"]
        print(f"✅ Successfully created repo and pushed all files.")
        
        enable_github_pages(repo.full_name, github_pat)
        return repo.html_url, commit.sha

    except Exception as e:
        # ... (error handling logic remains the same) ...
        print(f"❌ GitHub operation failed: {e}")
        return None, None

def poll_for_deployment(pages_url: str, nonce_to_check: str, timeout: int = 240):
    """
    Checks a URL at a fixed interval until it's live and contains a specific nonce.
    """
    print(f"📡 Polling {pages_url} for deployment...")
    print(f"   (Looking for nonce: {nonce_to_check})")
    
    # Load the fixed polling interval from .env, defaulting to 15 seconds
    try:
        polling_interval = int(os.getenv("POLLING_TIME", "15"))
    except ValueError:
        print("⚠️  Warning: POLLING_TIME in .env is not a valid number. Defaulting to 15s.")
        polling_interval = 15

    print(f"   (Checking every {polling_interval} seconds)")

    start_time = time.time()
    while time.time() - start_time < timeout:
        elapsed_time = time.time() - start_time
        try:
            response = requests.get(pages_url, timeout=10)
            
            if response.status_code == 200:
                nonce_meta_tag = f'<meta name="deployment-nonce" content="{nonce_to_check}">'
                if nonce_meta_tag in response.text:
                    print(f"✅ Deployment confirmed live after {elapsed_time:.0f} seconds!")
                    return True
                else:
                    print(f"   [{elapsed_time:.0f}s/{timeout}s] Site is live, but new content not yet visible. Waiting...")
            else:
                 print(f"   [{elapsed_time:.0f}s/{timeout}s] Site not ready (Status: {response.status_code}). Waiting...")
                 
        except requests.exceptions.RequestException:
            print(f"   [{elapsed_time:.0f}s/{timeout}s] Site not reachable yet. Retrying...")

        # Use the fixed interval loaded from the environment
        time.sleep(polling_interval)

    print(f"❌ Polling timed out after {timeout} seconds. Deployment failed.")
    return False

def send_callback(payload: dict, evaluation_url: str):
    """
    Sends the final payload to the evaluation URL with exponential backoff retry.
    """
    print(f"📞 Sending callback to {evaluation_url}...")
    
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = requests.post(evaluation_url, json=payload, timeout=15)
            if response.status_code == 200:
                print("✅ Callback successfully sent and acknowledged.")
                return True
            else:
                print(f"⚠️ Callback server returned an error (Status: {response.status_code}). Retrying...")
        
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Callback failed with connection error: {e}. Retrying...")
        
        if attempt < max_retries - 1:
            delay = 2 ** attempt # Exponential backoff: 1, 2, 4, 8 seconds
            print(f"   Waiting {delay}s before next attempt.")
            time.sleep(delay)
            
    print("❌ Failed to send callback after multiple retries.")
    return False

# In main.py
from github import Github, UnknownObjectException # Add UnknownObjectException for error handling

def fetch_and_update_repo(request_data: TaskRequest) -> (str, str):
    """
    Fetches an existing repo, updates its content based on a new brief, injects the new nonce, and returns the repo URL and commit SHA in a single commit.
    """
    repo_name = request_data.task
    print(f"🔄 Starting update process for repository: {repo_name}")
    github_pat = os.getenv("GITHUB_PAT")

    try:
        g = Github(github_pat)
        user = g.get_user()
        repo = user.get_repo(repo_name)
        
        # Fetch existing code for the revision prompt
        index_file = repo.get_contents("index.html")
        old_html_code = index_file.decoded_content.decode("utf-8")

        revision_brief = f"""
        Your task is to modify the following existing HTML code based on a new requirement.
        --- EXISTING CODE ---
        {old_html_code}
        --- END EXISTING CODE ---
        --- NEW REQUIREMENT ---
        {request_data.brief}
        --- END NEW REQUIREMENT ---
        The final, updated code must still pass these checks: {', '.join(request_data.checks)}.
        Respond with only the complete, new HTML code block and nothing else.
        """
        
        # --- FIX: Pass attachments to the LLM ---
        new_html_code = generate_code_with_llm(revision_brief, request_data.checks, request_data.attachments)
        if not new_html_code or new_html_code.startswith("<h1>Error"):
            raise Exception("LLM failed to generate a valid revision.")

        # --- OPTIMIZATION: Inject the new nonce BEFORE committing ---
        nonce_meta_tag = f'<meta name="deployment-nonce" content="{request_data.nonce}">'
        final_html_code = new_html_code.replace("</head>", f"    {nonce_meta_tag}\n</head>", 1)

        # --- FIX: Update the README.md file ---
        readme_file = repo.get_contents("README.md")
        new_readme_content = f"# {repo_name}\n\n**Latest Brief (Round {request_data.round}):**\n{request_data.brief}"
        repo.update_file(
            path="README.md", message=f"docs: update for round {request_data.round}",
            content=new_readme_content, sha=readme_file.sha, branch="main"
        )

        # Update the main index.html with the final code
        update_commit = repo.update_file(
            path="index.html", message=f"feat: apply round {request_data.round} revisions",
            content=final_html_code, sha=index_file.sha, branch="main"
        )["commit"]
        
        print("✅ Successfully updated repository in a single commit.")
        return repo.html_url, update_commit.sha

    except UnknownObjectException:
        print(f"❌ Error: The repository '{repo_name}' was not found for the update.")
        return None, None
    except Exception as e:
        print(f"❌ GitHub update operation failed: {e}")
        return None, None

# In main.py, replace your existing process_and_deploy_task function with this one

def process_and_deploy_task(request_data: TaskRequest):
    print(f"🚀 Starting background processing for task: {request_data.task}, Round: {request_data.round}")
    
    repo_name = request_data.task
    repo_url, commit_sha = None, None

    # --- Dispatch based on the round number ---
    if request_data.round == 1:
        html_code = generate_code_with_llm(request_data.brief, request_data.checks, request_data.attachments)
        if not html_code or html_code.startswith("<h1>Error"):
            print("❌ Halting task due to LLM code generation failure.")
            return
            
        nonce_meta_tag = f'<meta name="deployment-nonce" content="{request_data.nonce}">'
        html_code = html_code.replace("</head>", f"    {nonce_meta_tag}\n</head>", 1)
        
        # Call the updated function with attachments
        repo_url, commit_sha = create_and_push_to_github(
            repo_name, html_code, request_data.brief, request_data.attachments
        )
    
    else: # Handle Round 2 and any subsequent rounds
        # Call the new, optimized update function
        repo_url, commit_sha = fetch_and_update_repo(request_data)

    # --- Common logic for ALL rounds (remains unchanged) ---
    if not repo_url or not commit_sha:
        print(f"❌ Halting task for round {request_data.round} due to GitHub deployment failure.")
        return

    github_username = os.getenv("GITHUB_USERNAME")
    pages_url = f"https://{github_username}.github.io/{repo_name}/"
    
    is_live = poll_for_deployment(pages_url, request_data.nonce)
    if not is_live:
        print("❌ Halting task because deployment could not be verified.")
        return

    callback_payload = {
        "email": request_data.email, "task": request_data.task, "round": request_data.round,
        "nonce": request_data.nonce, "repo_url": repo_url, "commit_sha": commit_sha,
        "pages_url": pages_url,
    }
    send_callback(callback_payload, str(request_data.evaluation_url))
    
    print(f"✅ Finished processing for task: {request_data.task}, Round: {request_data.round}")

# --- API Endpoint ---
@app.post("/api-endpoint")
async def receive_task(request: TaskRequest, background_tasks: BackgroundTasks):
    # 1. Verify the secret
    if request.secret != MY_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret provided.")

    # 2. Add the deployment function to run in the background
    background_tasks.add_task(process_and_deploy_task, request)

    # 3. Immediately return a 200 OK response
    return {"message": "Request received. Processing will start in the background."}