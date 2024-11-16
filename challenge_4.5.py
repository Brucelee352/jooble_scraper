import requests as req
import time
import os
import pandas as pd
from dotenv import load_dotenv

load_dotenv("Documents/Python Projects/challenge_4.5.env")



# List needed to append, in order to store processed data 
key = os.getenv("KEY")

base_url = f'https://jooble.org/api/{key}'
headers = {"Content-type": "application/json"}


def jooble_list():
    job_list = []
    max_pages = 10  # Maximum number of pages to fetch
    num_pages = int(input("How many pages do you want to include in the results? "))
    page_count = min(num_pages, max_pages)  # Limit page count to `max_pages`
    max_attempts = 5
    

    for page in range(1, page_count + 1):
        params = {
            "keywords": "data engineer, analytics engineer",
            "location": "United States",
            "radius": "500",
            "page": str(page),
            "companysearch": "false"
        }
        print(f"Fetching data from URL: {base_url}")
        attempt = 0

        while attempt < max_attempts:
            try:
                response = req.post((f'{base_url}'), timeout=10, headers=headers, json=params)
                if response.status_code == 200:
                    print("Request valid!")
                    data = response.json()
                    job_results = data.get("jobs", [])
                        
                    if not job_results:  
                        print("No more jobs found.")
                        break
                        
                    for job in job_results:
                        job_list.append({
                           "id": job.get("id", "N/A"),
                            "title": job.get("title", "N/A"),
                            "company": job.get("company", "N/A"),
                            "location": job.get("location", "N/A"),
                            "salary": job.get("salary", "N/A"),
                            "job_type": job.get("type", "N/A"),
                            "snippet": job.get("snippet", "N/A"),
                            "link": job.get("link", "N/A"),
                            "updated": job.get("updated", "N/A"),
                            "source": job.get("source", "N/A")
                            })
                    break

                elif response.status_code == 429:
                    print("Rate limit reached, retrying in 30 seconds...")
                    attempt += 1
                    time.sleep(30)

                else:
                    print(f"Error! Status code: {response.status_code}")
                    return None

            except req.exceptions.RequestException as e:
                print(f"Request failed: {e}")
                attempt += 1

        if attempt >= max_attempts:
            print(f"Maximum retries reached for page {page}, skipping to next page.")
            continue
            
    print("Pagination complete!")

    df = pd.DataFrame(job_list)
    df['updated'] = pd.to_datetime(df['updated'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S')
    df['id'] = df['id'].astype(str).str.lstrip('-')
    df['id'] = pd.to_numeric(df['id'], errors='coerce')
    
    output_path = os.path.join(os.getcwd(), "Documents/job_list.csv")
    print(f"Saving results to {output_path}")
    df.to_csv(output_path, index=False)
    print(df)

jooble_list()