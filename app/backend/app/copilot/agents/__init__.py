"""
Specialist agents that work alongside the Copilot (the orchestrating agent).

  checker   - answer-checker: every number in a reply must trace back to measured/model data
  lot       - lot analyst: compares readings, finds outliers, plans which samples go to ICP
  report    - report writer: turns the session's results into a downloadable Word report
  speech    - voice: a short spoken summary of an answer for hands-free mode

The numeric work is deterministic and runs without any AI key; when Claude is configured it plans,
explains and (for the checker) repairs answers. No agent ever invents a measurement.
"""
