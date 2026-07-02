# jooble_scraper
A program to scour Jooble.org for job listings, which then collates the data into a tidy .csv — and now, a full Dash web app that puts those listings into a sortable table and plots them on a map of the US. This can be used with any IDE, but I used Virtual Studio Code with extensions. 

## Introduction
This was born out of a desire to share my projects with the public, I've been upskilling and looking for work for the last two years. I figured that perhaps, in addition to my own needs, maybe I could help my friends cut through a lot of the noise going on in the current labor market with this tool. 

What started as a single script has grown a bit: there's now a reusable data layer (`jooble_data.py`) that talks to the Jooble API, and a web interface (`app.py`) built with Plotly Dash that lets you pull up to 100 jobs posted within the last week (or just the last 2 days), browse them in a table, and see where they are on a map. The original script (`scraper_source.py`) is still here if all you want is the .csv. 

### First thing...
1. To get started, clone the repository.
2. Open MS Powershell, Git Bash or the windows command line; run them as administrator. 
3. Make sure the directory is set to your project folder using ```cd path/to/the/project/folder```.
4. Get your free API key here: https://jooble.org/api/about. 
5. Set it as the ```KEY``` environment variable, or edit/rename the 'example.env' file to '.env' with your key inside. 

**Note:** Use Python **3.12** for this project — the pinned version of pandas doesn't have wheels for 3.14 yet, so a newer install will fail on you. 

## Setting up a Virtual Environment

While you could just download the scripts themselves, copy/paste them into VS Code and configure the environments ad-hoc; I recommend setting up a virtual environment if you already use an IDE and want to sequester this from your global environment. Otherwise, ignore these steps. 

1. Creating the virtual environment:
Run ```py -3.12 -m venv venv``` in your command line tool of choice.

2. Activate venv within the command line:
- **Windows:**
  ```
  venv\Scripts\activate
  ```
- **Mac/Linux:**
  ```
  source venv/bin/activate
  ```

3. Run ```pip install -r requirements.txt```. This will install the needed libraries into your virtual environment, requirements.txt is included within the repository.

4. **Optional:**
Use deactivate in the command line to turn the virtual environment off.

## Running the web app
This is the fun part. With your key set, run:
```
python app.py
```
Then open http://127.0.0.1:8050 in your browser. Click 'Fetch jobs', type in whatever keywords and location you're after (they start out filled in with my data engineering defaults), pick your window (last 7 days or last 2 days), and hit fetch — you'll get a table you can sort, filter and click through to the actual postings, plus a map showing where the jobs are. Listings that can't be pinned to a location (remote roles, mostly) stay in the table but sit the map out. 

The app starts up fine without a key, it'll just remind you to set one before it can fetch anything. 

## Running the original script
The classic experience. With your key set, run ```python scraper_source.py```, tell it how many pages you want (up to 10), and it'll save the results to Documents/jooble_list.csv under the project folder. Make sure that Documents folder exists first, or the save will fail. 

## For the curious
There's a smoke-test harness under `.claude/skills/run-jooble-scraper/` that exercises everything against a mocked API — no key needed. Handy if you want to poke at the code without burning requests:
```
python .claude/skills/run-jooble-scraper/driver.py --module
python .claude/skills/run-jooble-scraper/ui_smoke.py
```
The data layer's contract lives in `INTERFACE.md` if you want to build something of your own on top of it. 

## To-Dos:
1. Code in the ability to send the output .csv as an email to yourself or others.
2. Maybe give the option to save the resulting dataset to .xlsx for further manipulation in Excel.
3. Add in Docker support for orchestration purposes. 
4. Smarter geocoding — right now the map works off a built-in list of major cities and state centers, so smaller towns land on their state's centroid. 
   
