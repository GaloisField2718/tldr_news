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

## TODO

Links are not effective for most of links. I'm still working to find a solution. Feel free to try any solutions. I hope to solve this issue as soon as possible :)

Automate treatment.
