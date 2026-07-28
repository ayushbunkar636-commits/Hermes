import sys
import os
import config

conn = config.get_db_connection()
c = conn.cursor()

c.execute("SELECT id, project_url, status FROM projects")
projects = c.fetchall()
print("PROJECTS:", projects)

c.execute("SELECT id, project_id, domain, next_scan_due, status FROM whitelist_sites")
sites = c.fetchall()
print("SITES:", sites)
