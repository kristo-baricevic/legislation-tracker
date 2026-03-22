# Legislation Tracker (frontend)

**Full-stack local setup (Postgres + Redis + Django + Celery + this app, without Docker):** see the **[root README](../README.md)**.

## Getting Started

First, run the development server (backend should be running separately if you use the API):

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

### Auth (login / sign up)

The app has **Log in** and **Sign up** pages that use the Django backend JWT API. To use them:

1. Run the backend (`legislation-tracker-backend`) and ensure it is available at `http://localhost:8000` (or set `NEXT_PUBLIC_API_URL` in `.env.local` to your backend URL).
2. Create an account at `/signup`, then log in at `/login`. The access token is stored in `localStorage`.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## govinfo api docs

<https://github.com/usgpo/api>
