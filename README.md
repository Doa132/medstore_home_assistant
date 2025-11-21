# medstore_home_assistant
Medication Storage custom component for Home Assistant

This component was written by ChatGPT, not me due to ignorance of how. I just tested it and pointed out issues until it worked.

It creates a master sensor for storing medication being taken, and relevant info about it. I use it to track how many pills and refills I have left per medication I take, and receive actionable notifications when it's time to take each medication.
```
sensor.medstore_data
	state: entries/medication count
	attributes:
		meds:
	      name: {{text}}
	      strength: {{text}}
	      dose: {{ number - pills to take each time}}
	      doses_per_day:{{ number - number of doses/day }}
	      timing: {{ list: ['00:00','01:00'] if 2 doses/day}}
	      doses_available: {{ number - current total pill count }}
	      refills_available: {{ number - current total script refills available}}
	      doses_per_refill: {{ number - pills gained each time a script is filled }}
	      next_refill: {{ date - auto calculated based on dose, doses_per_day and doses_available}}
	      taken_count_per_dose: {{ list: [0,1] showing if a times dose is taken. 0 is not, 1 is taken }}
	      all_taken: {{ boolean - auto set if all doses that day taken ie. taken_count_per_dose [1,1]}}
	      active: {{ boolean }}
```
In theory it also creates one entity per medication, however I've had issues with that that I can't be bothered understanding, deleting or fixing. 
I use template sensor instead to create these entities, as it allows me to create a state with the format: "Take {{dose}} pills at {{ timing[0] }} for use in dashboard card.
Also an attribute specifying which time is due next based on set rules.

Services created:
    add:
    description: "Add a medication (med_data should be a dict with med fields)"
    fields:
      med_data:
        description: "Medication dictionary (name, strength, dose, doses_per_day, timing, doses_available, refills_available, doses_per_refill, etc.)"

    delete:
      description: "Delete medication at index"
      fields:
        index:
          description: "Index number (0-based)"

    update:
      description: "Update medication fields at index"
      fields:
        index:
          description: "Index number (0-based)"
        updates:
          description: "Mapping of fields to update"

    toggle_active:
      description: "Toggle active state for medication at index"
      fields:
        index:
          description: "Index number (0-based)"

    take_dose:
      description: "Mark a dose taken for medication at index (decrease doses_available, set dose_index to '1' in taken_count_per_dose)"
      fields:
        index:
          description: "Index number (0-based)"
        dose_index:
          description: "Index into timing list (0-based)"

    add_refill:
      description: "Add refill (increase doses_available by doses_per_refill, decrease refills_available by 1) for med at index"
      fields:
        index:
          description: "Index number (0-based)"
        amount:
          description: "Number of doses to add (optional)"

<img width="684" height="870" alt="Example_dashboard" src="https://github.com/user-attachments/assets/d3b05630-fccf-424b-b13c-92220396101d" />
