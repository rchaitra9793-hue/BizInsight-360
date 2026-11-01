# Put BizInsight 360 on the internet (free, PythonAnywhere)

After these steps the app is live at `https://YOUR-USERNAME.pythonanywhere.com` and opens
on any phone or computer, with your PC switched off. Takes about 15 minutes.

In every command below, replace **`YOUR-USERNAME`** with your PythonAnywhere username.

---

## 1. Create a free account

Go to <https://www.pythonanywhere.com>, choose **Pricing & signup → Create a Beginner account**.
Your username becomes part of the web address.

## 2. Download the project and install it

Open **Consoles → Bash** and run these lines one at a time:

```bash
git clone https://github.com/rchaitra9793-hue/BizInsight-360.git
cd BizInsight-360
mkvirtualenv --python=python3.13 bizinsight
pip install -r requirements.txt
```

The install takes a few minutes. (If `python3.13` is not available, use the newest version
listed, 3.11 or later.)

## 3. Create the web app

1. Open the **Web** tab and click **Add a new web app** → **Next**.
2. Choose **Manual configuration** (not "Flask") → pick the **same Python version** as above → **Next**.
3. On the page that opens, fill in:
   - **Source code:** `/home/YOUR-USERNAME/BizInsight-360`
   - **Virtualenv:** `/home/YOUR-USERNAME/.virtualenvs/bizinsight`

## 4. Connect the app (WSGI file)

On the same **Web** tab, click the link next to **WSGI configuration file**. Delete everything
in that file and paste this, then click **Save**:

```python
import os
import sys

path = "/home/YOUR-USERNAME/BizInsight-360"
if path not in sys.path:
    sys.path.insert(0, path)

# Your own admin login - used when the database is created on first visit
os.environ["BIZ_ADMIN_EMAIL"] = "your-email@example.com"
os.environ["BIZ_ADMIN_PASSWORD"] = "choose-a-strong-password"
os.environ["BIZ_HTTPS"] = "1"

from app import app as application
```

Use a strong password here. Because it is not `admin123`, the demo login box will **not**
appear on the public login page.

## 5. Static files and HTTPS

Still on the **Web** tab:

- Under **Static files**, add: URL `/static/` → Directory `/home/YOUR-USERNAME/BizInsight-360/bizinsight/static`
- Under **Security**, turn **Force HTTPS** on.

## 6. Start it

Click the green **Reload** button at the top, then open `https://YOUR-USERNAME.pythonanywhere.com`.

The **first visit takes up to a minute** while the sample data loads. After that it is fast.
Sign in with the email and password from step 4.

---

## After it is live

| Task | How |
|---|---|
| Share it | Send the link; anyone can **Create an account** and view dashboards (read-only) |
| Give someone admin rights | They register, then you open **Account → Users** and set them to Admin |
| Change your password | **Account** page in the app |
| Use your own data | **Data import → Reset database → Start empty**, then upload your CSVs |
| Update after changing code on GitHub | Bash console: `cd BizInsight-360 && git pull`, then **Reload** on the Web tab |
| See errors | **Web** tab → **Error log** |

## Free plan limits

- Once every **3 months**, log in to PythonAnywhere and click **"Run until 3 months from today"**
  on the Web tab, or the site is paused.
- 512 MB disk and limited CPU: fine for this project and the sample data.

## Good to know

- Everyone who registers sees the **same data** as you. That is fine for the demo dataset;
  think before uploading real business data to a public site.
- The admin email and password in step 4 are only read when the database is first created.
  To change them later, use the **Account** page.
- `instance/` (database and secret key) lives only on the server and is never uploaded to GitHub.
