# `accounts` app

## Purpose

This app is the **identity and preferences** layer for the Legislation Tracker. It answers: *who is logged in?* and *what do they care about?* (topics, state, chamber) so the product can personalize feeds, emails, or filters later.

## How it works (plain English + tech)

- **Django** (the web framework) stores users in **PostgreSQL** via the **Django ORM** (the built-in way to read/write database rows as Python objects).
- **Custom user model** (`User`): people sign in with **email** instead of a username. That matches how the **REST API** and **JSON Web Tokens (JWT)** expect login: the backend issues short-lived **access tokens** and longer-lived **refresh tokens** (handled by **djangorestframework-simplejwt**).
- **UserPreference** links a user to optional **topics** (from the `legislation` app), **U.S. state** (two-letter code), and **chamber** (House/Senate). You can have several preference rows per user (e.g. follow multiple topics). `last_sent_at` is reserved for future newsletter/digest timing.

## What you’ll find here

| Piece | Role |
|--------|------|
| `User` | Account record; email is the login id. |
| `UserPreference` | Saved interests for personalization. |
| `RegisterView` | HTTP endpoint to create an account (`/api/auth/register/`). |

Authentication endpoints live in the project `config/urls.py` (token obtain/refresh), not inside this app’s folder, but they use this app’s `User` model.

## Who should read this

Anyone wiring **login/signup**, **JWT**, or **user preferences** in the API or client.
