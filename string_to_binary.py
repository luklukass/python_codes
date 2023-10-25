def convert_to_binary(string):
    binary_string = ""
    for char in string:
        if char.isupper():
            binary_string += "1"
        elif char.islower():
            binary_string += "0"
        else:
            binary_string += char  # Keep other characters unchanged
    return binary_string

input_string = 'HeLLo'
binary_result = convert_to_binary(input_string)
print(binary_result)