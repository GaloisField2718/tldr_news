# TLDR Newsletter

## Init 

This repo is built with `pipenv`.

Before to run you have to declare a `.env` file with this format : 
```
email = 'YOUR_EMAIL'
KEY = 'YOUR_PASSWORD'
```

For gmail account you should activate double-authentication (2FA) and setup an app passwords :  [Sign in with app passwords - Google Account Help](https://support.google.com/accounts/answer/185833?hl=en).

After this you can run this repo with :

```
pipenv shell
> pipenv install --ignore-pipfile
> python3 script.py
```

## Repository

The repository is structured around each categories from **TLDR newsletter**. Each email is saved in format `articles_{date_reception}.md` in corresponding folder.

The `ids.txt` file is used to save each email's id to be able to not do again the treatment if it's already done.

Some tests and archives and still in the repo. 

## Automation

To run automation I use `crontab -e` with the cronjob file content. 

Warning ! You have to authorise acces with `chmod +x automation.sh && chmod +x script_push.sh` to be able to use it.

## TODO

Improve render. We need to select the Title for each article add `(TITLE)` before `[LINK]`.


