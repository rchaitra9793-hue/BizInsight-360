"""Run BizInsight 360 locally:  python app.py  then open http://127.0.0.1:5000

Environment options:
  FLASK_DEBUG=1   auto-reload and error pages while developing (never on a shared network)
  HOST=0.0.0.0    let phones on the same Wi-Fi connect
  PORT=5000
"""
import os

from bizinsight import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG") == "1")
