# DeptCloud – Academic File Sharing Portal

## Overview

DeptCloud is a cloud-based academic file-sharing portal developed using Flask and Supabase. It allows students and faculty to access, upload, manage, search, and download academic documents through a centralized platform.

The project was developed as part of a Cloud Computing course.

## Technologies Used

- **Backend:** Python, Flask
- **Frontend:** HTML, CSS, Bootstrap, Jinja Templates
- **Database:** Supabase PostgreSQL
- **Authentication:** Supabase Auth
- **Cloud Storage:** Supabase Storage

## Features

- User registration and login
- Role-based access for Admin, Faculty, and Students
- Faculty document uploads
- Cloud-based document storage
- Search by document title and filtering by subject and semester
- Document version history
- Download previous and updated document versions
- Admin dashboard for managing user roles
- File type and size restrictions

## User Roles

- Student: Can view, search, and download documents.
- Faculty: Can upload documents and manage versions of their own documents.
- Admin: Can manage user roles and access faculty features.

## Project Structure

DeptCloud/
├── app.py
├── schema.sql
├── requirements.txt
├── README.md
├── .gitignore
├── .env.example
└── templates/
    ├── admin.html
    ├── auth.html
    ├── base.html
    ├── document.html
    ├── index.html
    └── upload.html

## Installation and Setup (Windows)

1. Install Python 3.11 or later.
2. Clone or download this repository.
3. Open the project folder in VS Code.
4. Create a virtual environment:

   `py -m venv .venv`

5. Activate the virtual environment:

   `.\.venv\Scripts\Activate.ps1`

6. Install dependencies:

   `pip install -r requirements.txt`

7. Create a Supabase project at https://supabase.com/dashboard.
8. Open the Supabase SQL Editor and execute `schema.sql` on a fresh project.
9. Copy `.env.example` to `.env` and configure the required environment variables.
10. Use the Supabase publishable/anon API key, not the service-role key.
11. Set a strong random `FLASK_SECRET_KEY`.
12. Configure email confirmation in Supabase Authentication for local testing.
13. Start the application:

   `python app.py`

14. Open `http://[::1]:8765` in your browser.

### Admin Setup

Register a user account, then execute the following in the Supabase SQL Editor:

```sql
update public.profiles
set role = 'admin'
where email = 'YOUR_EMAIL';
```

Sign out and sign in again. You can then use the Admin dashboard to assign faculty roles.

## Testing

The project was designed to support the following tests:

- Student registration and login
- Role-based restrictions for upload and admin pages
- Faculty document uploads
- Student document downloads
- Search and filtering
- Uploading and downloading multiple document versions
- Faculty ownership restrictions for version uploads
- Admin role management
- Rejection of unsupported files and files exceeding 10 MB

## Limitations

DeptCloud is an academic demonstration project and is not intended for production use.

The application requires an internet connection to Supabase. Additional security improvements such as CSRF protection, rate limiting, stronger file validation, and more detailed authorization would be required for institutional deployment.

Currently, authenticated users can access documents regardless of department. Document version updates are intended for sequential use.

## References

- [Flask Documentation](https://flask.palletsprojects.com/)
- [Supabase Documentation](https://supabase.com/docs)
- [Supabase Authentication](https://supabase.com/docs/guides/auth)
- [Supabase Storage](https://supabase.com/docs/guides/storage)
- [Bootstrap Documentation](https://getbootstrap.com/docs/5.3/)