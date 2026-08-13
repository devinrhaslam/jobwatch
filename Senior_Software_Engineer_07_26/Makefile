# Build with pdflatex, not xelatex. Both work — awesome-cv.cls branches on the
# engine — but only the pdflatex path emits real space characters into the PDF
# text layer (via \pdfinterwordspaceon in resume.tex). XeLaTeX's fontspec route
# writes glyph ids with kerning offsets and no spaces at all, so ATS parsers
# read "StaffSoftwareEngineer-HappyReturns" as one token and fail to find the
# company. Twice, for the page-fit and hyperref references.
resume:
	pdflatex -interaction=nonstopmode resume.tex
	pdflatex -interaction=nonstopmode resume.tex

# Confirm the text layer is still parseable. Words must come out separated.
check-ats: resume
	@gs -q -dNOPAUSE -dBATCH -sDEVICE=txtwrite -dTextFormat=3 -o - resume.pdf \
	  | grep -E "Happy Returns|Jido Maps" \
	  || (echo "FAIL: employer names did not extract as separate words"; exit 1)

clean:
	rm -f resume.aux resume.log resume.out build.log xe.log

test:
	cd examples/ ; for f in *.tex; do xelatex $$f; done

.PHONY: resume check-ats clean test
