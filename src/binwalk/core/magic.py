__all__ = ['Magic']

import re
import struct
import datetime
import binwalk.core.compat

class ParserException(Exception):
    pass

class SignatureTag(object):
    def __init__(self, **kwargs):
        for (k,v) in binwalk.core.compat.iterator(kwargs):
            setattr(self, k, v)

class SignatureResult(object):

    def __init__(self, **kwargs):
        # These are set by signature keyword tags
        self.jump = 0
        self.many = False
        self.size = 0
        self.name = None
        self.offset = 0
        self.strlen = 0
        self.string = False
        self.invalid = False
        self.extract = True

        # These are set by code internally
        self.id = 0
        self.file = None
        self.valid = True
        self.display = True
        self.description = ""

        for (k,v) in binwalk.core.compat.iterator(kwargs):
            setattr(self, k, v)

        self.valid = (not self.invalid)

class SignatureLine(object):

    def __init__(self, line):
        '''
        Class constructor. Responsible for parsing a line from a signature file.

        @line - A line from the signature file.

        Returns None.
        '''
        self.tags = []
        self.text = line

        # Split the line on any white space; for this to work, backslash-escaped
        # spaces ('\ ') are replaced with their escaped hex value ('\x20').
        parts = line.replace('\\ ', '\\x20').split(None, 3)

        # The indentation level is determined by the number of '>' characters at
        # the beginning of the signature line.
        self.level = parts[0].count('>')

        # Get rid of the indentation characters and try to convert the remaining
        # characters to an integer offset. This will fail if the offset is a complex
        # value (e.g., '(4.l+16)').
        self.offset = parts[0].replace('>', '')
        try:
            self.offset = int(self.offset, 0)
        except ValueError as e:
            pass

        self.type = parts[1]
        self.opvalue = None
        self.operator = None
        for operator in ['&', '|', '*', '+', '-', '/']:
            if operator in parts[1]:
                (self.type, self.opvalue) = parts[1].split(operator, 1)
                self.operator = operator
                try:
                    self.opvalue = int(self.opvalue, 0)
                except ValueError as e:
                    pass
                break

        if parts[2][0] in ['=', '!', '>', '<', '&', '|']:
            self.condition = parts[2][0]
            self.value = parts[2][1:]
        else:
            self.condition = '='
            self.value = parts[2]

        if self.value == 'x':
            self.value = None
        elif self.type == 'string':
            try:
                self.value = binwalk.core.compat.string_decode(self.value)
            except ValueError as e:
                raise ParserException("Failed to decode string value '%s' in line '%s'" % (self.value, line))
        else:
            self.value = int(self.value, 0)

        if len(parts) == 4:
            self.format = parts[3].replace('%ll', '%l')
            retag = re.compile(r'\{.*?\}')

            # Parse out tag keywords from the format string
            for tag in [m.group() for m in retag.finditer(self.format)]:
                tag = tag.replace('{', '').replace('}', '')
                if ':' in tag:
                    (n, v) = tag.split(':', 1)
                else:
                    n = tag
                    v = True
                self.tags.append(SignatureTag(name=n, value=v))

            # Remove tags from the printable format string
            self.format = retag.sub('', self.format).strip()
        else:
            self.format = ""

        if self.type[0] == 'u':
            self.signed = False
            self.type = self.type[1:]
        else:
            self.signed = True

        if self.type.startswith('be'):
            self.type = self.type[2:]
            self.endianess = '>'
        elif self.type.startswith('le'):
            self.endianess = '<'
            self.type = self.type[2:]
        else:
            self.endianess = '<'

        if self.type == 'string':
            self.fmt = None
            if self.value:
                self.size = len(self.value)
            else:
                self.size = 128
        elif self.type == 'byte':
            self.fmt = 'b'
            self.size = 1
        elif self.type == 'short':
            self.fmt = 'h'
            self.size = 2
        elif self.type == 'quad':
            self.fmt = 'q'
            self.size = 8
        else:
            self.fmt = 'i'
            self.size = 4

        if self.fmt:
            self.pkfmt = '%c%c' % (self.endianess, self.fmt)
        else:
            self.pkfmt = None

        if not self.signed:
            self.fmt = self.fmt.upper()

class Signature(object):

    def __init__(self, id, first_line):
        self.id = id
        self.lines = [first_line]
        self.title = first_line.format
        self.offset = first_line.offset
        self.confidence = first_line.size
        self.regex = self.generate_regex(first_line)

    def generate_regex(self, line):
        restr = ""

        if line.type in ['string']:
            restr = re.escape(line.value)
        elif line.size == 1:
            restr = re.escape(chr(line.value))
        elif line.size == 2:
            if line.endianess == '<':
                restr = re.escape(chr(line.value & 0xFF) + chr(line.value >> 8))
            elif line.endianess == '>':
                restr = re.escape(chr(line.value >> 8) + chr(line.value & 0xFF))
        elif line.size == 4:
            if line.endianess == '<':
                restr = re.escape(chr(line.value & 0xFF) +
                                  chr((line.value >> 8) & 0xFF) +
                                  chr((line.value >> 16) & 0xFF) +
                                  chr(line.value >> 24))
            elif line.endianess == '>':
                restr = re.escape(chr(line.value >> 24) +
                                  chr((line.value >> 16) & 0xFF) +
                                  chr((line.value >> 8) & 0xFF) +
                                  chr(line.value & 0xFF))
        elif line.size == 8:
            if line.endianess == '<':
                restr = re.escape(chr(line.value & 0xFF) +
                                  chr((line.value >> 8) & 0xFF) +
                                  chr((line.value >> 16) & 0xFF) +
                                  chr((line.value >> 24) & 0xFF) +
                                  chr((line.value >> 32) & 0xFF) +
                                  chr((line.value >> 40) & 0xFF) +
                                  chr((line.value >> 48) & 0xFF) +
                                  chr(line.value >> 56))
            elif line.endianess == '>':
                restr = re.escape(chr(line.value >> 56) +
                                  chr((line.value >> 48) & 0xFF) +
                                  chr((line.value >> 40) & 0xFF) +
                                  chr((line.value >> 32) & 0xFF) +
                                  chr((line.value >> 24) & 0xFF) +
                                  chr((line.value >> 16) & 0xFF) +
                                  chr((line.value >> 8) & 0xFF) +
                                  chr(line.value & 0xFF))

        return re.compile(restr)

    def append(self, line):
        self.lines.append(line)

class Magic(object):
    '''
    Primary class for loading signature files and scanning
    blocks of arbitrary data for matching signatures.
    '''

    def __init__(self, exclude=[], include=[], invalid=False):
        '''
        Class constructor.

        @include - A list of regex strings describing which signatures should be included in the scan results.
        @exclude - A list of regex strings describing which signatures should not be included in the scan results.
        @invalid - If set to True, invalid results will not be ignored.

        Returns None.
        '''
        # Used to save the block of data passed to self.scan (see additional comments in self.scan)
        self.data = ""
        # A list of Signature class objects, populated by self.parse (see also: self.load)
        self.signatures = []

        self.show_invalid = invalid
        self.includes = [re.compile(x) for x in include]
        self.excludes = [re.compile(x) for x in exclude]

        # Regex rule to replace backspace characters (an the preceeding character)
        # in formatted signature strings (see self._analyze).
        self.bspace = re.compile(".\\\\b")
        # Regex rule to match printable ASCII characters in formatted signature
        # strings (see self._analyze).
        self.printable = re.compile("[ -~]*")

    def _filtered(self, text):
        '''
        Tests if a string should be filtered out or not.

        @text - The string to check against filter rules.

        Returns True if the string should be filtered out, i.e., not displayed.
        Returns False if the string should be displayed.
        '''
        filtered = None
        # Text is converted to lower case first, partially for historical
        # purposes, but also because it simplifies writing filter rules
        # (e.g., don't have to worry about case sensitivity).
        text = text.lower()

        for include in self.includes:
            if include.match(text):
                filtered = False
                break

        # If exclusive include filters have been specified and did
        # not match the text, then the text should be filtered out.
        if self.includes and filtered == None:
            return True

        for exclude in self.excludes:
            if exclude.match(text):
                filtered = True
                break

        # If no explicit exclude filters were matched, then the
        # text should *not* be filtered.
        if filtered == None:
            filtered = False

        return filtered

    def _do_math(self, offset, expression):
        '''
        Parses and evaluates complex expressions, e.g., "(4.l+12)", "(6*32)", etc.

        @offset      - The offset inside self.data that the current signature starts at.
        @expressions - The expression to evaluate.

        Returns an integer value that is the result of the evaluated expression.
        '''
        # Does the expression contain an offset (e.g., "(4.l+12)")?
        if '.' in expression:
            # Split the offset field into the integer offset and type values (o and t respsectively)
            (o, t) = expression.split('.', 1)
            o = offset + int(o.split('(', 1)[1], 0)
            t = t[0]

            try:
                # Big and little endian byte format
                if t in ['b', 'B']:
                    v = struct.unpack('b', binwalk.core.compat.str2bytes(self.data[o:o+1]))[0]
                # Little endian short format
                elif t == 's':
                    v = struct.unpack('<h', binwalk.core.compat.str2bytes(self.data[o:o+2]))[0]
                # Little endian long format
                elif t == 'l':
                    v = struct.unpack('<i', binwalk.core.compat.str2bytes(self.data[o:o+4]))[0]
                # Big endian short format
                elif t == 'S':
                    v = struct.unpack('>h', binwalk.core.compat.str2bytes(self.data[o:o+2]))[0]
                # Bit endian long format
                elif t == 'L':
                    v = struct.unpack('>i', binwalk.core.compat.str2bytes(self.data[o:o+4]))[0]
            # struct.error is thrown if there is not enough bytes in self.data for the specified format type
            except struct.error as e:
                v = 0

            # Once the value at the specified offset is read from self.data, re-build the expression
            # (e.g., "(4.l+12)" might be converted into "(256+12)".
            v = "(%d%s" % (v, expression.split(t, 1)[1])
        # If no offset, then it's just an evaluatable math expression (e.g., "(32+0x20)")
        else:
            v = expression

        # Evaluate the final expression
        return binwalk.core.common.MathExpression(v).value

    def _analyze(self, signature, offset):
        '''
        Analyzes self.data for the specified signature data at the specified offset .

        @signature - The signature to apply to the data.
        @offset    - The offset in self.data to apply the signature to.

        Returns a dictionary of tags parsed from the data.
        '''
        description = []
        tag_strlen = None
        max_line_level = 0
        tags = {'id' : signature.id, 'offset' : offset, 'invalid' : False}

        # Apply each line of the signature to self.data, starting at the specified offset
        for line in signature.lines:
            # Ignore indentation levels above the current max indent level
            if line.level <= max_line_level:
                # If the relative offset of this signature line is just an integer value, use it
                if isinstance(line.offset, int):
                    line_offset = line.offset
                # Else, evaluate the complex expression
                else:
                    line_offset = self._do_math(offset, line.offset)

                # The start of the data needed by this line is at offset + line_offset.
                # The end of the data will be line.size bytes later.
                start = offset + line_offset
                end = start + line.size

                # If the line has a packed format string, unpack it
                if line.pkfmt:
                    try:
                        dvalue = struct.unpack(line.pkfmt, binwalk.core.compat.str2bytes(self.data[start:end]))[0]
                    # Not enough bytes left in self.data for the specified format size
                    except struct.error as e:
                        dvalue = 0
                # Else, this is a string
                else:
                    # Wildcard strings have line.value == None
                    if line.value is None:
                        # Check to see if this is a string whose size is known and has been specified on a previous
                        # signature line.
                        if [x for x in line.tags if x.name == 'string'] and binwalk.core.compat.has_key(tags, 'strlen'):
                            dvalue = self.data[start:(start+tags['strlen'])]
                        # Else, just terminate the string at the first newline, carriage return, or NULL byte
                        else:
                            dvalue = self.data[start:end].split('\x00')[0].split('\r')[0].split('\r')[0]
                    # Non-wildcard strings have a known length, specified in the signature line
                    else:
                        dvalue = self.data[start:end]

                # Some integer values have special operations that need to be performed on them
                # before comparison (e.g., "belong&0x0000FFFF"). Complex math expressions are
                # supported here as well.
                if isinstance(dvalue, int) and line.operator:
                    # If the operator value of this signature line is just an integer value, use it
                    if isinstance(line.opvalue, int):
                        opval = line.opvalue
                    # Else, evaluate the complex expression
                    else:
                        opval = self._do_math(offset, line.opvalue)

                    # Perform the specified operation
                    if line.operator == '&':
                        dvalue &= opval
                    elif line.operator == '|':
                        dvalue |= opval
                    elif line.operator == '*':
                        dvalue *= opval
                    elif line.operator == '+':
                        dvalue += opval
                    elif line.operator == '-':
                        dvalue -= opval
                    elif line.operator == '/':
                        dvalue /= opval

                # Does the data (dvalue) match the specified comparison?
                if ((line.value is None) or
                    (line.condition == '=' and dvalue == line.value) or
                    (line.condition == '>' and dvalue > line.value) or
                    (line.condition == '<' and dvalue < line.value) or
                    (line.condition == '!' and dvalue != line.value) or
                    (line.condition == '&' and (dvalue & line.value)) or
                    (line.condition == '|' and (dvalue | line.value))):

                    # Up until this point, date fields are treated as integer values,
                    # but we want to display them as nicely formatted strings.
                    if line.type == 'date':
                        ts = datetime.datetime.utcfromtimestamp(dvalue)
                        dvalue = ts.strftime("%Y-%m-%d %H:%M:%S")

                    # Format the description string
                    # TODO: This is too simplistic of a check. What if '%%' is in the format string?
                    if '%' in line.format:
                        desc = line.format % dvalue
                    else:
                        desc = line.format

                    # If there was any description string, append it to the list of description string parts
                    if desc:
                        description.append(desc)

                    # Process tag keywords specified in the signature line. These have already been parsed out of the
                    # original format string so that they can be processed separately from the printed description string.
                    for tag in line.tags:
                        # Format the tag string
                        # TODO: This is too simplistic of a check. What if '%%' is in the format string?
                        if isinstance(tag.value, str) and '%' in tag.value:
                            tags[tag.name] = tag.value % dvalue

                            # Some tag values are intended to be integer values, so try to convert them as such
                            try:
                                tags[tag.name] = int(tags[tag.name], 0)
                            except KeyboardInterrupt as e:
                                raise e
                            except Exception as e:
                                pass
                        else:
                            # Some tag values are intended to be integer values, so try to convert them as such
                            try:
                                tags[tag.name] = int(tag.value, 0)
                            except KeyboardInterrupt as e:
                                raise e
                            except Exception as e:
                                tags[tag.name] = tag.value

                    # Abort processing soon as this signature is marked invalid, unless invalid results
                    # were explicitly requested. This means that the sooner invalid checks are made in a
                    # given signature, the faster the scan can filter out false positives.
                    if not self.show_invalid and tags['invalid']:
                        break

                    # If this line satisfied its comparison, +1 the max indentation level
                    max_line_level = line.level + 1
                else:
                    # No match on the first line, abort
                    if line.level == 0:
                        break
                    else:
                        # If this line did not satisfy its comparison, then higher
                        # indentation levels will not be accepted.
                        max_line_level = line.level

        # Join the formatted description strings and remove backspace characters (plus the preceeding character as well)
        tags['description'] = self.bspace.sub('', " ".join(description))

        # This should never happen
        if not tags['description']:
            tags['display'] = False
            tags['invalid'] = True

        # If the formatted string contains non-printable characters, consider it invalid
        if self.printable.match(tags['description']).group() != tags['description']:
            tags['invalid'] = True

        return tags

    def scan(self, data, dlen=None):
        '''
        Scan a data block for matching signatures.

        @data - A string of data to scan.
        @dlen - If specified, signatures at offsets larger than dlen will be ignored.

        Returns a list of SignatureResult objects.
        '''
        results = []
        matched_offsets = set()

        # It's expensive in Python to pass large strings around to various functions.
        # Since data can potentially be quite a large string, make it available to other
        # methods via a class attribute so that it doesn't need to be passed around to
        # different methods over and over again.
        self.data = data

        # If dlen wasn't specified, search all of self.data
        if dlen is None:
            dlen = len(self.data)

        # Loop through each loaded signature
        for signature in self.signatures:
            # Use regex to search the data block for potential signature matches (fast)
            for match in signature.regex.finditer(self.data):
                # Take the offset of the start of the signature into account
                offset = match.start() - signature.offset
                # Signatures are orderd based on the length of their magic bytes (largest first).
                # If this offset has already been matched to a previous signature, ignore it unless
                # self.show_invalid has been specified. Also ignore obviously invalid offsets (<1)
                # as well as those outside the specified self.data range (dlen).
                if (offset not in matched_offsets or self.show_invalid) and offset >= 0 and offset <= dlen:
                    # Analyze the data at this offset using the current signature rule
                    tags = self._analyze(signature, offset)
                    # Generate a SignatureResult object and append it to the results list if the
                    # signature is valid, or if invalid results were requested.
                    if not tags['invalid'] or self.show_invalid:
                        results.append(SignatureResult(**tags))
                        # Add this offset to the matched_offsets set, so that it can be ignored by
                        # subsequent loops.
                        matched_offsets.add(offset)

        # Sort results by offset
        results.sort(key=lambda x: x.offset, reverse=False)

        return results

    def load(self, fname):
        '''
        Load signatures from a file.

        @fname - Path to signature file.

        Returns None.
        '''
        fp = open(fname, "r")
        lines = fp.readlines()
        self.parse(lines)
        fp.close()

    def parse(self, lines):
        '''
        Parse signature file lines.

        @lines - A list of lines from a signature file.

        Returns None.
        '''
        signature = None

        for line in lines:
            # Split at the first comment delimiter (if any) and strip the result
            line = line.split('#')[0].strip()
            # Ignore blank lines and lines that are nothing but comments
            if line:
                # Parse this signature line
                sigline = SignatureLine(line)
                # Level 0 means the first line of a signature entry
                if sigline.level == 0:
                    # If there is an existing signature, append it to the signature list,
                    # unless the text in its title field has been filtered by user-defined
                    # filter rules.
                    if signature:
                        if not self._filtered(signature.title):
                            self.signatures.append(signature)

                    # Create a new signature object; use the size of self.signatures to
                    # assign each signature a unique ID.
                    signature = Signature(len(self.signatures), sigline)
                # Else, just append this line to the existing signature
                elif signature:
                    signature.append(sigline)
                # If this is not the first line of a signature entry and there is no other
                # existing signature entry, something is very wrong with the signature file.
                else:
                    raise ParserException("Invalid signature line: '%s'" % line)

        # Add the final signature to the signature list
        if signature:
            if not self._filtered(signature.lines[0].format):
                self.signatures.append(signature)

        # Sort signatures by confidence (aka, length of their magic bytes), largest first
        self.signatures.sort(key=lambda x: x.confidence, reverse=True)

