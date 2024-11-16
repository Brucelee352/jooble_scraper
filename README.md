# jooble_scraper
A program to scour Jooble.org for job listings, which then collates the data into a tidy .csv. This can be used with any IDE, but I used Virtual Studio Code with extensions. 

## Introduction
This was born out of a desire to share my projects with the public, I've been upskilling and looking for work for the last two years. I figured that perhaps, in addition to my own needs, maybe I could help my friends cut through a lot of the noise going on in the current labor market with this tool. 

### First thing...
1. To get started, clone the repository.
2. Open MS Powershell, Git Bash or the windows command line; run them as administrator. 
3. Make sure the directory is set to your project folder using ```cd path/to/the/project/folder```. Then, run ```pip install -r requirements.txt```. This will install the needed libraries into your virtual environment, requirements.txt in included within the repository.
4. Edit/rename the 'example.env' file with the key that you'll need to obtain here: https://jooble.org/api/about. Make sure the paths match to where that .env file is in the source code. 


## Setting up a Virtual Environment

While you could just download the script itself, copy/paste it into VS Code, change the file paths and configure the environments ad-hoc; I recommend setting up a virtual environment if you already use an IDE and want to sequester this from your global environment. Otherwise, ignore these steps. 

1. Creating the virtual environment:
Run ```python -m venv venv``` in your command line tool of choice.

2. Activate venv within the command line:
- **Windows:**
  ```
  venv\Scripts\activate
  ```
- **Mac/Linux:**
  ```
  source venv/bin/activate
  ```

3. **Optional:**
Use deactivate in the command line to turn the virtual environment off.

4. Run the scraper_source.py:
The needed libraries and enviroment file should be configured, after that it's then a matter of opening the script and running it within your IDE.

## To-Dos:
1. Code in the ability to send the output .csv as an email to yourself or others.
2. Further refinements, adding logic to exit the program during loop sequences.
3. Maybe give the option to save the resulting dataset to .xlsx for further manipulation in Excel. 
   

