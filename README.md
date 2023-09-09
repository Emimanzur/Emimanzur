name: CI/CD Workflow for RE/MAX Social

on:
  push:
    branches: [ "SOCIAL" ]
  pull_request:
    branches: [ "SOCIAL" ]
  workflow_dispatch:

jobs:
  build-and-test:
    runs-on: ubuntu-latest

    steps:
    - name: Checkout code
      uses: actions/checkout@v2

    - name: Setup environment
      run: ./setup_environment.sh

    - name: Run tests
      run: ./run_tests.sh

  deploy:
    needs: build-and-test
    runs-on: ubuntu-latest

    steps:
    - name: Deploy to production
      run: ./deploy_production.sh

    - name: Notify team about deployment
      run: ./notify_team.sh "New build deployed to production"

  track-activities:
    runs-on: ubuntu-latest

    steps:
    - name: Track calls
      run: ./track_calls.sh

    - name: Track property uploads
      run: ./track_property_uploads.sh

    - name: Track client visits
      run: ./track_client_visits.sh

    - name: Track prelistings
      run: ./track_prelistings.sh

    - name: Track sign placements
      run: ./track_sign_placements.sh

    - name: Track captures
      run: ./track_captures.sh

    - name: Track sales
      run: ./track_sales.sh

    - name: Notify team about activity tracking
      run: ./notify_team.sh "Activities have been tracked and updated"

