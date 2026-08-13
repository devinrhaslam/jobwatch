\ProvidesClass{awesome-cv}[2015/12/14 v1.3 Awesome Curriculum Vitae Class]
\NeedsTeXFormat{LaTeX2e}


%-------------------------------------------------------------------------------
%                Class options
%
% (need to be done before the external package loading, for example because
% we need \paperwidth, \paperheight and \@ptsize to be defined before loading
% geometry and fancyhdr)
%-------------------------------------------------------------------------------
% Options for draft or final
\DeclareOption{draft}{\setlength\overfullrule{5pt}}
\DeclareOption{final}{\setlength\overfullrule{0pt}}
% Inherit options of article
\DeclareOption*{
  \PassOptionsToClass{\CurrentOption}{article}
}
\ProcessOptions\relax
\LoadClass{article}


%-------------------------------------------------------------------------------
%                3rd party packages
%-------------------------------------------------------------------------------
% Needed to make fixed length table
\RequirePackage{array}
% Needed to handle list environment
\RequirePackage{enumitem}
% Needed to handle text alignment
\RequirePackage{ragged2e}
% Needed to configure page layout
\RequirePackage{geometry}
% Needed to make header & footer effeciently
\RequirePackage{fancyhdr}
% Needed to manage colors
\RequirePackage{xcolor}
% Needed to use \ifxetex-\else-\fi statement
\RequirePackage{ifxetex}
% Needed to use \if-\then-\else statement
\RequirePackage{xifthen}
% Needed to use a toolbox of programming tools
\RequirePackage{etoolbox}
% Needed to change line spacing in specific environment
\RequirePackage{setspace}
% Needed to manage fonts
\ifxetex
  \RequirePackage[quiet]{fontspec}
  % To support LaTeX quoting style
  \defaultfontfeatures{Ligatures=TeX}
\else
  \RequirePackage[T1]{fontenc}
  % Replace by the encoding you are using
  \RequirePackage[utf8]{inputenc}
\fi
% Needed to manage math fonts
\ifxetex\RequirePackage[math-style=TeX]{unicode-math}\fi
% Needed to use icons from font-awesome
% (https://github.com/posquit0/latex-fontawesome)
\ifxetex
  \RequirePackage{fontawesome}
\else
  \RequirePackage{fontawesome5}
  \providecommand{\faLinkedinSquare}{\faLinkedin}
\fi
% Needed to deal a paragraphs
\RequirePackage{parskip}
% Needed to deal hyperlink
\RequirePackage{hyperref}
\hypersetup{
  pdftitle={},
  pdfauthor={},
  pdfsubject={},
  pdfkeywords={},
  colorlinks=false,
  allbordercolors=white
}


%-------------------------------------------------------------------------------
%                Configuration for directory locations
%-------------------------------------------------------------------------------
% Configure a directory location for fonts(default: 'fonts/')
\newcommand*{\fontdir}[1][fonts/]{\def\@fontdir{#1}}
\fontdir


%-------------------------------------------------------------------------------
%                Configuration for layout
%-------------------------------------------------------------------------------
%% Page Layout
% Configure page margins with geometry
\geometry{left=2.0cm, top=1.5cm, right=2.0cm, bottom=2.0cm, footskip=.5cm}

%% Header & Footer
% Set offset to each header and offset
\fancyhfoffset{0em}
% Remove head rule
\renewcommand{\headrulewidth}{0pt}
% Clear all header & footer fields
\fancyhf{}
% Enable if you want to make header or footer using fancyhdr
\pagestyle{fancy}


% Text colors
\definecolor{darktext}{HTML}{414141}
\colorlet{text}{darkgray}
\colorlet{graytext}{gray}
\colorlet{lighttext}{lightgray}

\ifxetex
\newfontfamily\headerfont[
  Path=\@fontdir,
  UprightFont=*-Regular,
  ItalicFont=*-Italic,
  BoldFont=*-Bold,
  BoldItalicFont=*-BoldItalic,
]{Roboto}

\newfontfamily\headerfontlight[
  Path=\@fontdir,
  UprightFont=*-Thin,
  ItalicFont=*-ThinItalic,
  BoldFont=*-Medium,
  BoldItalicFont=*-MediumItalic,
]{Roboto}

% Set font for footer (default is Source Sans Pro)
\newfontfamily\footerfont[
  Path=\@fontdir,
  UprightFont=*-Regular,
  ItalicFont=*-It,
  BoldFont=*-Bold
]{SourceSansPro}

\newfontfamily\regularSans[
  Path=\@fontdir,
  UprightFont=*-Regular,
  ItalicFont=*-It,
  BoldFont=*-Bold
]{SourceSansPro}

\newfontfamily\lightSans[
  Path=\@fontdir,
  UprightFont=*-Light,
  ItalicFont=*-It,
  BoldFont=*-Bold
]{SourceSansPro}

\newfontfamily\boldSans[
  Path=\@fontdir,
  UprightFont=*-Bold,
  ItalicFont=*-It,
  BoldFont=*-Bold
]{SourceSansPro}

\newfontfamily\semiboldSans[
  Path=\@fontdir,
  UprightFont=*-Semibold,
  ItalicFont=*-It,
  BoldFont=*-Bold
]{SourceSansPro}

% Set font for body (default is Source Sans Pro)
\newfontfamily\bodyfont[
  Path=\@fontdir,
  UprightFont=*-Regular,
  ItalicFont=*-It,
  BoldFont=*-Bold,
  BoldItalicFont=*-BoldIt
]{SourceSansPro}

\newfontfamily\bodyfontlight[
  Path=\@fontdir,
  UprightFont=*-Light,
  ItalicFont=*-LightIt,
  BoldFont=*-Semibold,
  BoldItalicFont=*-SemiboldIt
]{SourceSansPro}
\else
  \RequirePackage[nosfdefault]{sourcesanspro}
  \RequirePackage{roboto}
  \renewcommand{\familydefault}{SourceSansPro-TLF}
  \newcommand{\headerfont}{\fontfamily{Roboto-TLF}\fontseries{m}\selectfont}
  \newcommand{\headerfontlight}{\fontfamily{Roboto-TLF}\fontseries{thin}\selectfont}
  \newcommand{\footerfont}{\fontfamily{SourceSansPro-TLF}\fontseries{m}\selectfont}
  \newcommand{\regularSans}{\fontfamily{SourceSansPro-TLF}\fontseries{m}\selectfont}
  \newcommand{\lightSans}{\fontfamily{SourceSansPro-TLF}\fontseries{l}\selectfont}
  \newcommand{\boldSans}{\fontfamily{SourceSansPro-TLF}\fontseries{b}\selectfont}
  \newcommand{\semiboldSans}{\fontfamily{SourceSansPro-TLF}\fontseries{sb}\selectfont}
  \newcommand{\bodyfont}{\fontfamily{SourceSansPro-TLF}\fontseries{m}\selectfont}
  \newcommand{\bodyfontlight}{\fontfamily{SourceSansPro-TLF}\fontseries{l}\selectfont}
\fi


%-------------------------------------------------------------------------------
%                Configuration for styles
%-------------------------------------------------------------------------------

% Header!
\newcommand*{\headerfirstnamestyle}[1]{{\fontsize{36pt}{1em}\headerfontlight\color{graytext} #1}}
\newcommand*{\headerlastnamestyle}[1]{{\fontsize{36pt}{1em}\headerfont\bfseries\color{text} #1}}
\newcommand*{\headerpositionstyle}[1]{{\fontsize{12pt}{1em}\bodyfont\scshape\color{awesome} #1}}
\newcommand*{\headersocialstyle}[1]{{\fontsize{10pt}{1em}\headerfont\color{text} #1}}

% Section!
\newcommand*{\sectionstyle}[1]{{\fontsize{18pt}{1em}\bodyfont\bfseries\color{black}#1}}
\newcommand*{\entrytitlestylexx}[1]{{\fontsize{13pt}{1em}\bodyfont\bfseries\color{darktext} #1 \vspace{1.2mm}}}
\newcommand*{\entrylocationstylexx}[1]{{\fontsize{10pt}{1em}\bodyfontlight\slshape\color{awesome} #1 \vspace{1.5mm}}}
\newcommand*{\descriptionstylexx}[1]{{\fontsize{12pt}{1em}\bodyfontlight\upshape\color{text} #1}}

% Skills!
\newcommand*{\skilltypestyle}[1]{{\fontsize{13pt}{1em}\bodyfont\bfseries\color{darktext} #1}}
\newcommand*{\skillsetstyle}[1]{{\fontsize{12pt}{1em}\bodyfontlight\color{text} #1}}

\newcommand*{\name}[2]{\def\@firstname{#1}\def\@lastname{#2}}
\newcommand*{\firstname}[1]{\def\@firstname{#1}}
\newcommand*{\lastname}[1]{\def\@lastname{#1}}
\newcommand*{\familyname}[1]{\def\@lastname{#1}}
\def\@familyname{\@lastname}

% Define writer's position
% Usage: \name{<position>}
\newcommand*{\position}[1]{\def\@position{#1}}

% Defines writer's email (optional)
% Usage: \email{<email adress>}
\newcommand*{\email}[1]{\def\@email{#1}}

% Defines writer's github (optional)
% Usage: \github{<github-nick>}
\newcommand*{\github}[1]{\def\@github{#1}}

% Defines writer's linked-in (optional)
% Usage: \linkedin{<linked-in-nick>}
\newcommand*{\linkedin}[1]{\def\@linkedin{#1}}

% Defines the separator between social info items in header (default: ' | ')
% Usage: \headersocialsep[\quad\textbar\quad]
\newcommand*{\headersocialsep}[1][ | ]{\def\@headersocialsep{#1}}
\headersocialsep


%-------------------------------------------------------------------------------
%                Commands for utilities
%-------------------------------------------------------------------------------
% Use to align an element of tabular table
\newcolumntype{L}[1]{>{\raggedright\let\newline\\\arraybackslash\hspace{0pt}}m{#1}}
\newcolumntype{C}[1]{>{\centering\let\newline\\\arraybackslash\hspace{0pt}}m{#1}}
\newcolumntype{R}[1]{>{\raggedleft\let\newline\\\arraybackslash\hspace{0pt}}m{#1}}

% Use to draw horizontal line with specific tickness
\def\vhrulefill#1{\leavevmode\leaders\hrule\@height#1\hfill \kern\z@}

% Use to execute conditional statements by checking empty string
\newcommand*{\ifempty}[3]{\ifthenelse{\isempty{#1}}{#2}{#3}}


%-------------------------------------------------------------------------------
%                Commands for elements of CV structure
%-------------------------------------------------------------------------------
% Define a header for CV
% Usage: \makecvheader
\newcommand*{\makecvheader}{
  \begin{center}
    \headerfirstnamestyle{
      \@firstname
    } \headerlastnamestyle{
      \@lastname
    }
    \\
    \vspace{2.4mm}
    \ifthenelse{\isundefined{\@position}}{}{\headerpositionstyle{\@position\\}}
    \vspace{2.4mm}
    \ifthenelse{\isundefined{\@address}}{}{\headeraddressstyle{\@address\\}}
    \vspace{-0.5mm}
    \headersocialstyle{
      \newbool{isstart}
      \setbool{isstart}{true}
      \ifthenelse{\isundefined{\@email}}
        {}
        {
          \ifbool{isstart}
            {
              \setbool{isstart}{false} 
            }
            {\@headersocialsep}
          \href{mailto:\@email}{\faEnvelope\ \@email}
        }
      \ifthenelse{\isundefined{\@github}}
        {}
        {
          \ifbool{isstart}
            {
              \setbool{isstart}{false} 
            }
            {\@headersocialsep}
          \href{https://github.com/\@github}{\faGithubSquare\ github.com/\@github}
        }
      \ifthenelse{\isundefined{\@linkedin}}
        {}
        {
          \ifbool{isstart}
            {
              \setbool{isstart}{false} 
            }
            {\@headersocialsep}
          \href{https://www.linkedin.com/in/\@linkedin}{\faLinkedinSquare\ linkedin.com/in/\@linkedin}
        }
    }
  \end{center}
}

% Define a section for CV
% Usage: \cvsection{<section-title>}
\newcommand{\cvsection}[1]{
  \par\addvspace{2.5ex}
  \phantomsection{}
  \sectionstyle{#1}
  \color{gray}\vhrulefill{0.9pt}
  \par\nobreak\addvspace{1.5ex}
}

% Define a subsection for CV
% Usage: \cvsubsection{<subsection-title>}
\newcommand{\cvsubsection}[1]{
  \phantomsection{}
  \subsectionstyle{#1}
}

% Define an environment for cventry
\newenvironment{cventries}{
  \begin{center}
}{
  \end{center}
}

% Define an environment for cventry
\newenvironment{cventriesx}{
  \begin{center}
}{
  \end{center}
}

\newcommand*{\cventryp}[5]{
  \setlength\tabcolsep{0pt}
  \setlength{\extrarowheight}{0pt}
  \begin{tabular*}{\textwidth}{@{\extracolsep{\fill} } L{12.5cm} R{4.5cm}}
      \entrytitlestylexx{#2} & \entrylocationstylexx{#3} \\
    \multicolumn{2}{L{17cm}}{\descriptionstylexx{#5}} \\
  \end{tabular*}
}

% Define an entry of cv information
% Usage: \cventry{<position>}{<title>}{<location>}{<date>}{<description>}
\newcommand*{\cventryr}[5]{
  \setlength\tabcolsep{0pt}
  \setlength{\extrarowheight}{0pt}
    \vspace{3mm}
      \descriptionstylexx{#5}
}

% Define an environment for cvskill
\newenvironment{cvskills}{
  \begin{center}
    \setlength\tabcolsep{1ex}
    \setlength{\extrarowheight}{4pt}
    \begin{tabular*}{\textwidth}{@{\extracolsep{\fill}} l L{12.0cm}}
}{
    \end{tabular*}
  \end{center}
}
% Define a line of cv information(skill)
% Usage: \cvskill{<type>}{<skillset>}
\newcommand*{\cvskill}[2]{
	\skilltypestyle{#1} & \skillsetstyle{#2} 
  \\
}

% Define an environment for cvitems(for cventry)
\newenvironment{cvitems}{
  \vspace{-4mm}
  \begin{justify}
  \begin{itemize}[leftmargin=2ex, nosep, noitemsep]
    \setlength{\parskip}{0pt}
    \renewcommand{\labelitemi}{\textbullet}
}{
  \end{itemize}
  \end{justify}
  \vspace{-5mm}
}
