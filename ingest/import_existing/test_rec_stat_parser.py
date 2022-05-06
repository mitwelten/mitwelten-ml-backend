import re

tests = {
    # MICROPHONE_CHANGED
    'RECORDING_OKAY-MICROPHONE_CHANGED-old': [
        "microphone change",
        "Recording cancelled before completion due to microphone change."
    ],
    'RECORDING_OKAY-MICROPHONE_CHANGED-1.6': [
        "microphone change",
        "Recording stopped due to microphone change."
    ],
    'RECORDING_OKAY-MICROPHONE_CHANGED-1.7': [
        "microphone change",
        "Recording stopped due to microphone change."
    ],
    # SWITCH_CHANGED
    'RECORDING_OKAY-SWITCH_CHANGED-old': [
        "change of switch position",
        "Recording cancelled before completion due to change of switch position."
    ],
    'RECORDING_OKAY-SWITCH_CHANGED-1.6': [
        "switch position change",
        "Recording stopped due to switch position change."
    ],
    'RECORDING_OKAY-SWITCH_CHANGED-1.7': [
        "switch position change",
        "Recording stopped due to switch position change."
    ],
    # SUPPLY_VOLTAGE_LOW
    'RECORDING_OKAY-SUPPLY_VOLTAGE_LOW-old': [
        "low voltage",
        "Recording cancelled before completion due to low voltage."
    ],
    'RECORDING_OKAY-SUPPLY_VOLTAGE_LOW-1.6': [
        "low voltage",
        "Recording stopped due to low voltage."
    ],
    'RECORDING_OKAY-SUPPLY_VOLTAGE_LOW-1.7': [
        "low voltage",
        "Recording stopped due to low voltage."
    ],
    # MAGNETIC_SWITCH
    'RECORDING_OKAY-MAGNETIC_SWITCH-1.7': [
        "magnetic switch",
        "Recording stopped by magnetic switch."
    ],
    # FILE_SIZE_LIMITED
    'RECORDING_OKAY-FILE_SIZE_LIMITED-old': [
        "file size limit",
        "Recording cancelled before completion due to file size limit."
    ],
    'RECORDING_OKAY-FILE_SIZE_LIMITED-1.6': [
        "file size limit",
        "Recording stopped due to file size limit."
    ],
    'RECORDING_OKAY-FILE_SIZE_LIMITED-1.7': [
        "file size limit",
        "Recording stopped due to file size limit."
    ]
}

if __name__ == '__main__':
    for key, test in tests.items():
        rec_nok = re.search(r"Recording (?:cancelled before completion|stopped) (?:by|due to) (magnetic switch|microphone change|change of switch position|switch position change|low voltage|file size limit)\.", test[1])[1]
        if rec_nok == test[0]:
            print('PASS:', key)
        else:
            print('FAIL:', key, f"--> {rec_nok} != {test[0]}")
